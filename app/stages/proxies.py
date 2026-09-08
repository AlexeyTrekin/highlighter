"""Proxies: small previews of every candidate, for a human to judge quickly.

A review page that streams 1080p source files is unusable — fifty of them will not play at
once, and the reviewer is making a snap decision per clip, not inspecting pixels. Each
candidate gets a 360p loop and a filmstrip; the strip is what the page falls back to when a
proxy is missing, and it is also what a vision model would be shown
(`spec/005_scoring.md`).
"""

from pathlib import Path

import cv2
import numpy as np

from app.manifests.candidates import Candidate
from app.manifests.project import Project, source_by_id
from app.video import ffmpeg

STAGE = "proxies"

PROXY_HEIGHT: int = 360
PROXY_CRF: str = "30"
STRIP_FRAMES: int = 5
STRIP_TILE_WIDTH: int = 320
POSTER_WIDTH: int = 640


def proxy_path(root: Path, candidate_id: str) -> Path:
    return root / "proxies" / f"{candidate_id}.mp4"


def strip_path(root: Path, candidate_id: str) -> Path:
    return root / "strips" / f"{candidate_id}.jpg"


def poster_path(root: Path, candidate_id: str) -> Path:
    return root / "posters" / f"{candidate_id}.jpg"


def _write_image(target: Path, image: np.ndarray) -> None:
    """Encode to a temp name and rename.

    The resume path accepts any non-empty file, so an interrupted run that left half a JPEG
    behind would be skipped forever and the page would show a broken image
    (`spec/003_pipeline.md`).
    """
    partial = target.with_suffix(".part.jpg")
    if cv2.imwrite(str(partial), image):
        partial.replace(target)


def build_proxy(source: Path, candidate: Candidate, target: Path) -> None:
    """A short, silent, low-resolution loop of the candidate's window.

    Written to a temp name and renamed, so an interrupted run leaves nothing the resume path
    would mistake for a finished proxy.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part.mp4")
    ffmpeg.run(
        [
            "-ss",
            f"{candidate.start:.3f}",
            "-t",
            f"{max(0.1, candidate.end - candidate.start):.3f}",
            "-i",
            str(source),
            "-an",
            "-vf",
            f"scale=-2:{PROXY_HEIGHT}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            PROXY_CRF,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(partial),
        ]
    )
    partial.replace(target)


def build_poster(source: Path, candidate: Candidate, target: Path) -> None:
    """One frame from the middle of the window, shown before the clip plays.

    A `<video>` with `preload="metadata"` renders nothing until it is played, so without this
    the page is a grid of black rectangles — and triaging fifty clips means seeing them all at
    once, not hovering over each in turn to find out what it is.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source))
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, (candidate.start + candidate.end) * 500)
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok:
        return

    height = round(POSTER_WIDTH * frame.shape[0] / frame.shape[1])
    _write_image(target, cv2.resize(frame, (POSTER_WIDTH, height)))


def build_strip(source: Path, candidate: Candidate, target: Path) -> None:
    """Five frames spread across the window, side by side.

    Sampled with OpenCV rather than ffmpeg because the frames are wanted as an image, not a
    video, and the seek cost of five frames is nothing next to spawning a process.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source))
    tiles: list[np.ndarray] = []
    try:
        span = max(0.0, candidate.end - candidate.start)
        for index in range(STRIP_FRAMES):
            fraction = (index + 0.5) / STRIP_FRAMES
            capture.set(cv2.CAP_PROP_POS_MSEC, (candidate.start + fraction * span) * 1000)
            ok, frame = capture.read()
            if not ok:
                break
            height = round(STRIP_TILE_WIDTH * frame.shape[0] / frame.shape[1])
            tiles.append(cv2.resize(frame, (STRIP_TILE_WIDTH, height)))
    finally:
        capture.release()

    if not tiles:
        return
    _write_image(target, np.hstack(tiles))


def strips_only(project: Project, candidates: list[Candidate], root: Path) -> list[str]:
    """Filmstrips without proxies, for candidates the pipeline already dropped.

    They are shown so one can be rescued, and a still is enough to judge that — transcoding
    eighty clips nobody intends to use is not.
    """
    built: list[str] = []
    for candidate in candidates:
        strip = strip_path(root, candidate.id)
        if strip.exists() and strip.stat().st_size > 0:
            continue
        build_strip(Path(source_by_id(project, candidate.source_id).path), candidate, strip)
        built.append(candidate.id)
    return built


def run(project: Project, candidates: list[Candidate], root: Path) -> list[str]:
    """Build a proxy and a strip for each candidate that lacks one.

    Resumable per candidate: fifty transcodes is minutes, and losing them because the last one
    failed would make the checkpoint pointless (`spec/003_pipeline.md`).
    """
    built: list[str] = []
    for candidate in candidates:
        source = Path(source_by_id(project, candidate.source_id).path)
        proxy = proxy_path(root, candidate.id)
        strip = strip_path(root, candidate.id)
        poster = poster_path(root, candidate.id)

        # Counted once per candidate that gained anything, so the number the CLI prints means
        # "clips whose previews were built" rather than "proxies", which would report zero for
        # a resumed run that filled in every missing poster.
        work = False
        if not proxy.exists() or proxy.stat().st_size == 0:
            build_proxy(source, candidate, proxy)
            work = True
        if not strip.exists() or strip.stat().st_size == 0:
            build_strip(source, candidate, strip)
            work = True
        if not poster.exists() or poster.stat().st_size == 0:
            build_poster(source, candidate, poster)
            work = True
        if work:
            built.append(candidate.id)
    return built
