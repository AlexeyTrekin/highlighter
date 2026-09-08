"""Ingest: register input files as project sources.

Sources are named `vNN` in sorted-filename order and that mapping is stable for the life of
the project — a re-run never renumbers an existing source, because every downstream manifest
refers to clips by that id.
"""

from pathlib import Path

from app.manifests.project import Project, Source, classify_shape
from app.video import ffmpeg

STAGE = "ingest"
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}


def collect(paths: list[Path]) -> list[Path]:
    """Expand directories into the video files inside them, sorted by name."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found += [p for p in path.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES]
        elif path.suffix.lower() in VIDEO_SUFFIXES:
            found.append(path)
    return sorted(found, key=lambda p: p.name)


def describe(path: Path, source_id: str) -> Source:
    info = ffmpeg.probe(path)
    stream = ffmpeg.video_stream(info)
    duration = ffmpeg.duration_s(info)
    return Source(
        id=source_id,
        original_name=path.name,
        path=str(path.resolve()),
        duration_s=duration,
        fps=ffmpeg.frame_rate(stream),
        width=int(stream["width"]),
        height=int(stream["height"]),
        shape=classify_shape(duration),
    )


def run(project: Project, paths: list[Path]) -> Project:
    """Add every input under `paths` that is not already registered."""
    known = {source.original_name for source in project.sources}
    next_index = len(project.sources) + 1

    for path in collect(paths):
        if path.name in known:
            continue
        project.sources.append(describe(path, f"v{next_index:02d}"))
        known.add(path.name)
        next_index += 1

    return project
