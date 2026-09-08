"""Stage orchestration: what runs, in what order, and what may be skipped.

Every stage is resumable at the unit of its output file, so a rerun is a no-op unless forced
(`spec/003_pipeline.md`).
"""

import datetime
from pathlib import Path

from app import project as project_store
from app.manifests import base
from app.manifests.analysis import Analysis
from app.manifests.candidates import Candidates
from app.manifests.edl import Edl
from app.manifests.music import Music
from app.manifests.project import Project
from app.manifests.qa import Qa
from app.manifests.review import Review
from app.stages import analyze as analyze_stage
from app.stages import candidates as candidates_stage
from app.stages import director as director_stage
from app.stages import music as music_stage
from app.stages import proxies as proxies_stage
from app.stages import qa as qa_stage
from app.stages import render as render_stage

ORDER: tuple[str, ...] = (
    "analyze",
    "music",
    "candidates",
    "proxies",
    "director",
    "render",
)


class StageBlocked(RuntimeError):
    """A stage cannot run because a prerequisite is missing."""


def load_music(root: Path) -> Music:
    path = project_store.music_path(root)
    if not path.is_file():
        raise StageBlocked("music.json is missing; run the music stage first")
    return base.read(path, Music)


def load_candidates(root: Path) -> Candidates:
    path = project_store.candidates_path(root)
    if not path.is_file():
        raise StageBlocked("candidates.json is missing; run the candidates stage first")
    return base.read(path, Candidates)


def load_edl(root: Path) -> Edl:
    path = project_store.edl_path(root)
    if not path.is_file():
        raise StageBlocked("edl.json is missing; run the director stage first")
    return base.read(path, Edl)


def run_music(root: Path, project: Project) -> Music:
    if not project.music_path:
        raise StageBlocked("this project has no music track; pass --music at init")
    music = music_stage.run(Path(project.music_path))
    base.write(project_store.music_path(root), music)
    return music


def run_analyze(root: Path, project: Project, force: bool = False) -> None:
    """Decode every source that has not been analysed yet.

    Resumable per source: this is the only stage that reads whole videos, and re-doing an
    hour of it because the last file failed would make the checkpoint pointless. `--force`
    has to reach in here rather than stopping at the stage boundary — without it the CLI
    reports the stage ran while every source was skipped, and a detector change silently
    leaves the whole project on stale numbers.
    """
    for source in project.sources:
        target = analyze_stage.analysis_path(root, source.id)
        if target.is_file() and not force:
            continue
        base.write(target, analyze_stage.analyse(source))


def load_analyses(root: Path, project: Project) -> dict[str, Analysis]:
    found: dict[str, Analysis] = {}
    for source in project.sources:
        path = analyze_stage.analysis_path(root, source.id)
        if not path.is_file():
            raise StageBlocked(f"{path.name} is missing; run the analyze stage first")
        found[source.id] = base.read(path, Analysis)
    return found


def run_candidates(root: Path, project: Project) -> Candidates:
    found = candidates_stage.run(project, load_music(root), load_analyses(root, project))
    base.write(project_store.candidates_path(root), found)
    return found


def run_proxies(root: Path, project: Project, force: bool = False) -> list[str]:
    usable = [c for c in load_candidates(root).candidates if not c.flags]
    dropped = [c for c in load_candidates(root).candidates if c.flags]
    # Dropped candidates get a filmstrip but no proxy: the page shows them so one can be
    # rescued, and a still is enough to judge that (`spec/007_review_ui.md`).
    return proxies_stage.run(project, usable, root) + proxies_stage.strips_only(
        project, dropped, root
    )


def load_review(root: Path) -> Review:
    path = project_store.review_path(root)
    return base.read(path, Review) if path.is_file() else Review()


def run_director(root: Path, project: Project) -> Edl:
    music, candidates, review = load_music(root), load_candidates(root), load_review(root)
    edl = director_stage.run(project, music, candidates, review)
    base.write(project_store.edl_path(root), edl)
    return edl


def director_conflicts(root: Path, project: Project) -> list[tuple[str, str]]:
    """Keeps the last director run could not honour."""
    return director_stage.unhonoured_keeps(
        project, load_music(root), load_candidates(root), load_review(root), load_edl(root)
    )


def run_render(root: Path, project: Project) -> Qa:
    edl = load_edl(root)
    reel = project_store.reel_path(root, project_store.next_reel_version(root))
    renders = render_stage.run(project, edl, project_store.render_dir(root), reel)
    report = qa_stage.run(edl, load_music(root), renders, project.options.duration_s, project)
    base.write(project_store.qa_path(root), report)
    return report


# Stages whose own outputs are per-unit checkpoints, so `--force` has to be handed down to
# them rather than stopping at the stage boundary.
RUNNERS = {
    "analyze": run_analyze,
    "music": lambda root, project, force=False: run_music(root, project),
    "candidates": lambda root, project, force=False: run_candidates(root, project),
    "proxies": run_proxies,
    "director": lambda root, project, force=False: run_director(root, project),
    "render": lambda root, project, force=False: run_render(root, project),
}


def superseded(root: Path, project: Project, stage: str) -> bool:
    """Whether a completed stage rests on an input rewritten after it finished.

    Only the director has one: `review.json` is written by the review server, outside any run,
    and a stage that finished before the human made their decisions has not been run against
    them. Without this the sequence that the whole review step exists for — run, review, run —
    reports "nothing (already done)" and delivers the pre-review edit.

    `finished_at` is recorded to the second, so a review saved in the same second as the
    director finished reads as newer. Re-cutting a deterministic EDL costs nothing; missing the
    user's verdicts costs them the reel.
    """
    if stage != director_stage.STAGE:
        return False
    finished = project_store.stage_status(project, stage).finished_at
    review = project_store.review_path(root)
    if finished is None or not review.is_file():
        return False
    return review.stat().st_mtime > datetime.datetime.fromisoformat(finished).timestamp()


def run(root: Path, project: Project, stages: tuple[str, ...], force: bool) -> list[str]:
    """Run `stages` in order, skipping completed ones unless forced.

    A stage whose input was rewritten earlier in this same pass is not a completed stage, so it
    runs again: skipping it would hand the user a reel built from the previous EDL and call the
    run successful. That is narrower than invalidating downstream work in general, which
    `--force` on a single stage still leaves to the warning in the CLI (`spec/003_pipeline.md`).

    Status is recorded before and after each stage so an interrupted run stays visible as
    `running` rather than being mistaken for one that never started.
    """
    executed: list[str] = []
    for stage in stages:
        settled = project_store.is_done(project, stage) and not superseded(root, project, stage)
        if settled and not force and not executed:
            continue
        project_store.mark_running(root, project, stage)
        try:
            RUNNERS[stage](root, project, force)
        except Exception as error:
            project_store.mark_failed(root, project, stage, str(error))
            raise
        project_store.mark_done(root, project, stage)
        executed.append(stage)
    return executed
