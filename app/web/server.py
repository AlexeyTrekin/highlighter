"""The review server.

Local, loopback-bound, and serving media only from the project directory it was started for.
It records what the human did and decides nothing itself (`spec/007_review_ui.md`).
"""

import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import pipeline
from app import project as project_store
from app.manifests import base
from app.manifests.candidates import Candidate
from app.manifests.review import Review, Trim, Verdict, verdict_for
from app.stages import proxies as proxies_stage

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
STATIC_DIR = Path(__file__).parent / "static"

MEDIA_KINDS = {"proxies": ".mp4", "strips": ".jpg", "posters": ".jpg"}


class VerdictUpdate(BaseModel):
    verdict: Verdict


class TrimUpdate(BaseModel):
    start: float
    end: float


class NoteUpdate(BaseModel):
    note: str


def review_path(root: Path) -> Path:
    return root / "review.json"


def load_review(root: Path) -> Review:
    path = review_path(root)
    return base.read(path, Review) if path.is_file() else Review()


def save_review(root: Path, review: Review) -> None:
    review.updated_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    base.write(review_path(root), review)


def create_app(root: Path) -> FastAPI:
    """Build the server for one project.

    The project is bound at construction rather than taken per request: this serves the
    machine's own files, and a directory parameter in the URL would be an invitation to read
    the filesystem.
    """
    app = FastAPI(title="hlreel review", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        project = project_store.load(root)
        candidates = pipeline.load_candidates(root).candidates
        review = load_review(root)
        usable = [c for c in candidates if not c.flags]
        dropped = [c for c in candidates if c.flags]
        return TEMPLATES.TemplateResponse(
            request,
            "review.html",
            {
                "project": project,
                "usable": [_card(c, review, root) for c in usable],
                "dropped": [_card(c, review, root) for c in dropped],
                "reviewed": sum(1 for c in usable if c.id in review.verdicts),
                "completed": review.completed,
            },
        )

    @app.get("/media/{kind}/{candidate_id}")
    def media(kind: str, candidate_id: str):
        """Serve one proxy or filmstrip.

        Both path parts are checked against a fixed vocabulary rather than joined onto the
        project directory: this process can read everything the user can, and the only thing
        standing between the port and their filesystem is this function.
        """
        if kind not in MEDIA_KINDS:
            raise HTTPException(status_code=404, detail="unknown media kind")
        if not _is_candidate_id(candidate_id):
            raise HTTPException(status_code=404, detail="unknown candidate")

        path = root / kind / f"{candidate_id}{MEDIA_KINDS[kind]}"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="not built")
        return FileResponse(path)

    @app.put("/api/verdict/{candidate_id}")
    def set_verdict(candidate_id: str, update: VerdictUpdate):
        review = load_review(root)
        review.verdicts[_known(root, candidate_id)] = update.verdict
        save_review(root, review)
        return {"ok": True, "verdict": update.verdict}

    @app.put("/api/trim/{candidate_id}")
    def set_trim(candidate_id: str, update: TrimUpdate):
        if update.end <= update.start:
            raise HTTPException(status_code=400, detail="trim end must follow its start")
        review = load_review(root)
        review.trims[_known(root, candidate_id)] = Trim(start=update.start, end=update.end)
        save_review(root, review)
        return {"ok": True}

    @app.delete("/api/trim/{candidate_id}")
    def clear_trim(candidate_id: str):
        review = load_review(root)
        review.trims.pop(_known(root, candidate_id), None)
        save_review(root, review)
        return {"ok": True}

    @app.put("/api/note/{candidate_id}")
    def set_note(candidate_id: str, update: NoteUpdate):
        review = load_review(root)
        identifier = _known(root, candidate_id)
        if update.note.strip():
            review.notes[identifier] = update.note.strip()
        else:
            review.notes.pop(identifier, None)
        save_review(root, review)
        return {"ok": True}

    @app.post("/api/complete")
    def complete():
        review = load_review(root)
        review.completed = True
        save_review(root, review)
        return {"ok": True}

    return app


def _card(candidate: Candidate, review: Review, root: Path) -> dict:
    """What the page needs about one candidate."""
    trim = review.trims.get(candidate.id)
    return {
        "id": candidate.id,
        "source_id": candidate.source_id,
        "start": candidate.start,
        "end": candidate.end,
        "duration": candidate.end - candidate.start,
        "score": candidate.score,
        "material": candidate.material,
        "origin": candidate.origin,
        "flags": candidate.flags,
        "reason": candidate.agent.reason if candidate.agent else "",
        "verdict": verdict_for(review, candidate.id),
        "note": review.notes.get(candidate.id, ""),
        "trim": {"start": trim.start, "end": trim.end} if trim else None,
        "has_proxy": proxies_stage.proxy_path(root, candidate.id).is_file(),
        "has_strip": proxies_stage.strip_path(root, candidate.id).is_file(),
        "has_poster": proxies_stage.poster_path(root, candidate.id).is_file(),
    }


def _is_candidate_id(value: str) -> bool:
    return len(value) == 4 and value[0] == "c" and value[1:].isdigit()


def _known(root: Path, candidate_id: str) -> str:
    """Reject a verdict on a candidate that does not exist.

    Otherwise a typo silently accumulates entries the director will never look at, and
    `review.json` stops describing the project it belongs to.
    """
    if not _is_candidate_id(candidate_id):
        raise HTTPException(status_code=404, detail="unknown candidate")
    known = {c.id for c in pipeline.load_candidates(root).candidates}
    if candidate_id not in known:
        raise HTTPException(status_code=404, detail="unknown candidate")
    return candidate_id
