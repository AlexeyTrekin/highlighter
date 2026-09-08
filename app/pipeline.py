"""Stage orchestration: what runs, in what order, and what may be skipped.

Every stage is resumable at the unit of its output file, so a rerun is a no-op unless forced
(`spec/003_pipeline.md`).
"""

from pathlib import Path

from app import project as project_store
from app.manifests import base
from app.manifests.candidates import Candidates
from app.manifests.edl import Edl
from app.manifests.music import Music
from app.manifests.project import Project
from app.manifests.qa import Qa
from app.stages import candidates as candidates_stage
from app.stages import director as director_stage
from app.stages import music as music_stage
from app.stages import qa as qa_stage
from app.stages import render as render_stage

ORDER: tuple[str, ...] = ("music", "candidates", "director", "render")


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


def run_candidates(root: Path, project: Project) -> Candidates:
    found = candidates_stage.run(project, load_music(root))
    base.write(project_store.candidates_path(root), found)
    return found


def run_director(root: Path, project: Project) -> Edl:
    edl = director_stage.run(project, load_music(root), load_candidates(root))
    base.write(project_store.edl_path(root), edl)
    return edl


def run_render(root: Path, project: Project) -> Qa:
    edl = load_edl(root)
    reel = project_store.reel_path(root, project_store.next_reel_version(root))
    renders = render_stage.run(project, edl, project_store.render_dir(root), reel)
    report = qa_stage.run(edl, load_music(root), renders, project.options.duration_s)
    base.write(project_store.qa_path(root), report)
    return report


RUNNERS = {
    "music": run_music,
    "candidates": run_candidates,
    "director": run_director,
    "render": run_render,
}


def run(root: Path, project: Project, stages: tuple[str, ...], force: bool) -> list[str]:
    """Run `stages` in order, skipping completed ones unless forced.

    Status is recorded before and after each stage so an interrupted run stays visible as
    `running` rather than being mistaken for one that never started.
    """
    executed: list[str] = []
    for stage in stages:
        if project_store.is_done(project, stage) and not force:
            continue
        project_store.mark_running(root, project, stage)
        try:
            RUNNERS[stage](root, project)
        except Exception as error:
            project_store.mark_failed(root, project, stage, str(error))
            raise
        project_store.mark_done(root, project, stage)
        executed.append(stage)
    return executed
