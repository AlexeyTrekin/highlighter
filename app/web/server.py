"""The review server.

Local, loopback-bound, and serving media only from the project directory it was started for.
It records what the human did and decides nothing itself (`spec/007_review_ui.md`).
"""

import datetime
import threading
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import pipeline
from app import project as project_store
from app.manifests import base
from app.manifests import review as review_schema
from app.manifests.candidates import Candidate
from app.manifests.review import DEFAULT_VERDICT, Order, Review, Trim, Verdict, verdict_for
from app.stages import proxies as proxies_stage

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
STATIC_DIR = Path(__file__).parent / "static"

MEDIA_KINDS = {"proxies": ".mp4", "strips": ".jpg", "posters": ".jpg"}

# The page saves per keystroke and per slider move, and a browser runs several of those at
# once. Every write is a read-modify-write of one file, so without this two overlapping saves
# both read the same `review.json`, the second wins, and the first decision is gone while the
# page shows both as saved — the one failure `spec/007_review_ui.md` rules out.
_WRITE_LOCK = threading.Lock()


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


def edit_review(root: Path, mutate: Callable[[Review], None]) -> None:
    """Apply one change to `review.json`, serialised against every other change."""
    with _WRITE_LOCK:
        review = load_review(root)
        mutate(review)
        save_review(root, review)


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
                # Counted the same way the page recounts it after a click, and the same way
                # `review.touched` reports it to the agent: a candidate explicitly set back to
                # "agent's call" has not been ruled on.
                "reviewed": sum(1 for c in usable if verdict_for(review, c.id) != DEFAULT_VERDICT),
                "bar_s": _bar_s(root),
                "order": review.order.model_dump_json(),
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
        identifier = _known(root, candidate_id).id

        def apply(review: Review) -> None:
            review.verdicts[identifier] = update.verdict

        edit_review(root, apply)
        return {"ok": True, "verdict": update.verdict}

    @app.put("/api/trim/{candidate_id}")
    def set_trim(candidate_id: str, update: TrimUpdate):
        """Narrow a candidate's window.

        Bounded by the window itself: a trim binds on everything downstream
        (`spec/007_review_ui.md`), so one that reaches outside the examined footage would give
        the renderer seconds nothing has looked at while reading as the user's own choice.
        """
        candidate = _known(root, candidate_id)
        if update.end <= update.start:
            raise HTTPException(status_code=400, detail="trim end must follow its start")
        if update.start < candidate.start - 1e-6 or update.end > candidate.end + 1e-6:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"trim must stay inside the window {candidate.start:.2f}-{candidate.end:.2f}s"
                ),
            )

        def apply(review: Review) -> None:
            review.trims[candidate.id] = Trim(start=update.start, end=update.end)

        edit_review(root, apply)
        return {"ok": True}

    @app.delete("/api/trim/{candidate_id}")
    def clear_trim(candidate_id: str):
        identifier = _known(root, candidate_id).id

        def apply(review: Review) -> None:
            review.trims.pop(identifier, None)

        edit_review(root, apply)
        return {"ok": True}

    @app.put("/api/note/{candidate_id}")
    def set_note(candidate_id: str, update: NoteUpdate):
        identifier = _known(root, candidate_id).id

        def apply(review: Review) -> None:
            if update.note.strip():
                review.notes[identifier] = update.note.strip()
            else:
                review.notes.pop(identifier, None)

        edit_review(root, apply)
        return {"ok": True}

    @app.put("/api/order")
    def set_order(update: Order):
        """Record how the user wants the reel ordered.

        Written whole rather than per clip: a sequence is one statement, and applying it in
        pieces would leave `review.json` describing an order the user never asked for if a save
        in the middle failed.
        """
        known = {c.id for c in pipeline.load_candidates(root).candidates}
        # Every field, not only the ones this mode reads: an id the active mode ignores is still
        # written to `review.json`, still reaches the page, and still becomes live the moment
        # the user switches mode.
        named = {*update.sequence, *update.opening, *update.ending, *update.weights}
        unknown = sorted(named - known)
        if unknown:
            raise HTTPException(status_code=404, detail=f"unknown candidate {unknown[0]}")
        out_of_range = sorted(
            cid
            for cid, weight in update.weights.items()
            if not review_schema.WEIGHT_MIN <= weight <= review_schema.WEIGHT_MAX
        )
        if out_of_range:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"weight for {out_of_range[0]} is outside "
                    f"{review_schema.WEIGHT_MIN:.0f}-{review_schema.WEIGHT_MAX:.0f}"
                ),
            )

        edit_review(root, lambda review: setattr(review, "order", update))
        return {"ok": True}

    @app.post("/api/complete")
    def complete():
        edit_review(root, lambda review: setattr(review, "completed", True))
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


def _bar_s(root: Path) -> float | None:
    """The bar length the trim handles snap to, or nothing before the music stage has run."""
    try:
        return pipeline.load_music(root).grid.bar_s
    except pipeline.StageBlocked:
        return None


# `cNNN`, with no ceiling on N: a project with a thousand candidates numbers them `c1000`, and
# a length test would start refusing every write for those. ASCII digits only — `str.isdigit`
# also accepts `²` and `٠`, which are not path separators but have no business here either.
def _is_candidate_id(value: str) -> bool:
    digits = value[1:]
    return 1 < len(value) <= 8 and value[0] == "c" and digits.isascii() and digits.isdigit()


def _known(root: Path, candidate_id: str) -> Candidate:
    """The candidate this request names, or a 404.

    A verdict on a candidate that does not exist would silently accumulate entries the director
    never looks at, and `review.json` would stop describing the project it belongs to.
    """
    if not _is_candidate_id(candidate_id):
        raise HTTPException(status_code=404, detail="unknown candidate")
    found = {c.id: c for c in pipeline.load_candidates(root).candidates}.get(candidate_id)
    if found is None:
        raise HTTPException(status_code=404, detail="unknown candidate")
    return found
