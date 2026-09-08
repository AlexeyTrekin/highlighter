"""Ingest: register input files as project sources.

Sources are named `vNN` in sorted-filename order and that mapping is stable for the life of
the project — a re-run never renumbers an existing source, because every downstream manifest
refers to clips by that id.
"""

from pathlib import Path

import cv2

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


SIGNATURE_W: int = 16
SIGNATURE_H: int = 9
SIGNATURE_LEVELS: int = 16


def signature(path: Path, duration_s: float) -> list[int]:
    """A coarse thumbnail of a mid-file frame, for spotting the same recording twice.

    A checksum would not work: a clip re-uploaded through a messenger is re-encoded, and every
    byte changes. What survives that is the picture at low resolution — the 16x9 downscale
    averages away the compression noise — so the comparison happens there. Quantising to 16
    levels afterwards bounds how far one cell can move, which is what makes a mean distance
    comparable between pairs (`qa.DUPLICATE_TOLERANCE`). Taken from the middle of the file,
    away from the title cards and black frames that cluster at the edges.
    """
    capture = cv2.VideoCapture(str(path))
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, duration_s * 500)
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok:
        return []

    small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (SIGNATURE_W, SIGNATURE_H))
    step = 256 // SIGNATURE_LEVELS
    return [int(value) // step for value in small.flatten()]


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
        signature=signature(path, duration),
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
