"""The project directory: paths, stage status, and the lock that keeps writers single.

The directory is the whole state of a project (`spec/002_manifests.md`); there is no database.
"""

import datetime
import os
from pathlib import Path

from app.manifests import base
from app.manifests.project import Project, StageStatus

MANIFEST_NAME = "project.json"
LOCK_NAME = ".lock"


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def manifest_path(root: Path) -> Path:
    return root / MANIFEST_NAME


def render_dir(root: Path) -> Path:
    return root / "render"


def candidates_path(root: Path) -> Path:
    return root / "candidates.json"


def music_path(root: Path) -> Path:
    return root / "music.json"


def edl_path(root: Path) -> Path:
    return root / "edl.json"


def qa_path(root: Path) -> Path:
    return render_dir(root) / "qa.json"


def reel_path(root: Path, version: int) -> Path:
    return root / f"highlight_v{version}.mp4"


def next_reel_version(root: Path) -> int:
    """One past the highest reel already delivered.

    Reels are versioned rather than overwritten because comparing a new cut against the last
    one is how the edit gets judged — the whole of this project's design came out of holding
    two prototype reels side by side.
    """
    existing = [
        int(p.stem.removeprefix("highlight_v"))
        for p in root.glob("highlight_v*.mp4")
        if p.stem.removeprefix("highlight_v").isdigit()
    ]
    return max(existing, default=0) + 1


def latest_reel(root: Path) -> Path | None:
    version = next_reel_version(root) - 1
    return reel_path(root, version) if version >= 1 else None


def exists(root: Path) -> bool:
    return manifest_path(root).is_file()


def load(root: Path) -> Project:
    if not exists(root):
        raise FileNotFoundError(f"no project at {root} (run `hlreel init` first)")
    return base.read(manifest_path(root), Project)


def save(root: Path, project: Project) -> None:
    base.write(manifest_path(root), project)


def create(root: Path, project: Project) -> Project:
    """Write a new project, refusing to overwrite one that already exists.

    Source ids are stable for the life of a project and every other manifest refers to clips
    by them, so silently resetting `sources` would leave `candidates.json` and `edl.json`
    pointing at ids that no longer mean what they did.
    """
    if exists(root):
        raise FileExistsError(f"{root} is already a project; delete it or pick another directory")
    root.mkdir(parents=True, exist_ok=True)
    save(root, project)
    return project


def stage_status(project: Project, stage: str) -> StageStatus:
    return project.stages.get(stage, StageStatus())


def is_done(project: Project, stage: str) -> bool:
    return stage_status(project, stage).status == "done"


def mark_running(root: Path, project: Project, stage: str) -> None:
    project.stages[stage] = StageStatus(status="running", started_at=now())
    save(root, project)


def mark_done(root: Path, project: Project, stage: str) -> None:
    started = stage_status(project, stage).started_at
    project.stages[stage] = StageStatus(status="done", started_at=started, finished_at=now())
    save(root, project)


def mark_failed(root: Path, project: Project, stage: str, error: str) -> None:
    started = stage_status(project, stage).started_at
    project.stages[stage] = StageStatus(
        status="failed", started_at=started, finished_at=now(), error=error
    )
    save(root, project)


def acquire_lock(root: Path) -> Path:
    """Take the project lock, or fail saying who holds it.

    Stages write manifests that later stages read; two of them running at once on the same
    project produces a directory whose parts disagree. One writer per project directory.
    """
    root.mkdir(parents=True, exist_ok=True)
    lock = root / LOCK_NAME
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder = lock.read_text(encoding="utf-8").strip() or "an unknown process"
        raise RuntimeError(
            f"project {root} is locked by {holder}; remove {lock} if that process is gone"
        ) from None
    with os.fdopen(fd, "w") as handle:
        handle.write(f"pid {os.getpid()} at {now()}")
    return lock


def release_lock(root: Path) -> None:
    (root / LOCK_NAME).unlink(missing_ok=True)
