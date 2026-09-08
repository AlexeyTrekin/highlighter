"""Render: turn the EDL into the reel.

The edit is a deterministic function of `edl.json` — no cut point, clip length or crop comes
from anywhere else. `project.json` supplies only where the source files and the track live
(`spec/003_pipeline.md`).
"""

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.manifests.edl import Clip, Edl, Output, frame_counts
from app.manifests.project import Project, source_by_id
from app.video import decode, ffmpeg

STAGE = "render"

INTERMEDIATE_CRF: str = "12"
FADE_S: float = 1.2
# How long a killed encoder gets to die before we stop waiting for it.
ENCODER_SHUTDOWN_S: int = 30


@dataclass
class ClipRender:
    """What rendering one clip produced, including the signals QA needs."""

    clip: Clip
    path: Path
    frames: int
    brightness: list[float] = field(default_factory=list)
    tail_identical: int = 0

    @property
    def observed_frames(self) -> int:
        """Frames actually in the clip, one brightness sample per frame.

        Distinct from `frames`, which is what the timeline asked for. A truncated file makes
        them disagree, and that disagreement is what stops a short clip from sliding every
        later cut off the beat.
        """
        return len(self.brightness)


def clip_path(root: Path, clip: Clip, output: Output) -> Path:
    """Where a clip's rendered file lives.

    The name carries a digest of everything that affects the pixels, so a re-cut EDL cannot
    reuse a cached file from the previous one. Caching by position would silently serve the
    old clip at the new slot — a stale reel that looks freshly rendered.
    """
    # Only what changes this clip's pixels. Everything else on the clip — which slot it holds,
    # its section, its score, why it was chosen — can change without the picture changing, and
    # hashing it would re-render the whole reel every time the director is re-tuned.
    payload = json.dumps(
        {
            "source": clip.source_id,
            "in": clip.in_,
            "out": clip.out,
            "bars": clip.bars,
            "crop": clip.crop.model_dump(),
            "speed": clip.speed,
            "stabilize": clip.stabilize,
            "frame": [output.width, output.height, output.fps],
        },
        sort_keys=True,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    return root / f"c{clip.grid_slot:03d}_{digest}.mp4"


def inspect_rendered(clip: Clip, path: Path, frames: int, fps: int) -> ClipRender:
    """Measure an already-rendered clip so QA can judge it.

    A resumed render skips clips that exist, and reporting "no flashes" for a clip nothing
    looked at would be a false pass. These frames have been through stabilisation, so a
    repeated frame is only near-identical rather than exact.
    """
    brightness: list[float] = []
    previous = None
    tail_identical = 0
    capture = decode.open_capture(path)
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            brightness.append(decode.mean_brightness(frame))
            if previous is not None and decode.nearly_identical(frame, previous):
                tail_identical += 1
            else:
                tail_identical = 0
            previous = frame
    finally:
        capture.release()
    return ClipRender(
        clip=clip, path=path, frames=frames, brightness=brightness, tail_identical=tail_identical
    )


def is_complete(path: Path, frames: int) -> bool:
    """Whether a cached clip holds every frame its slot needs.

    A clip is written atomically, so a file at the final name should be whole — this is the
    second line of defence, because a short clip is invisible downstream: it concatenates
    happily and slides every later cut off the beat.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    capture = cv2.VideoCapture(str(path))
    try:
        # A file the decoder cannot open is incomplete, not fatal: the answer is to render it
        # again, and raising here would abort a resume over a clip we were about to replace.
        if not capture.isOpened():
            return False
        counted = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()
    return counted == frames


def render_clip(
    clip: Clip, source_path: Path, target: Path, frames: int, width: int, height: int, fps: int
) -> ClipRender:
    """Decode, frame, stabilise and encode one clip.

    Frames come from a fresh decode of the source; a crop is taken from the decoded frame and
    never from an already-cropped one, which is what produced a zoomed-in flash every fifth
    frame on 24 fps sources in the prototype (`spec/008_render.md`).
    """
    intermediate = target.with_suffix(".raw.mp4")
    transforms = target.with_suffix(".trf")
    # Encoding lands on a temp name and is renamed into place, so an interrupted render leaves
    # no half-written file at a name the resume path would trust.
    partial = target.with_suffix(".part.mp4")

    encoder = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            INTERMEDIATE_CRF,
            "-pix_fmt",
            "yuv420p",
            str(intermediate),
        ],
        stdin=subprocess.PIPE,
    )

    brightness: list[float] = []
    previous: np.ndarray | None = None
    tail_identical = 0
    try:
        if encoder.stdin is None:
            raise ffmpeg.FfmpegError("could not open a pipe to the encoder")
        for frame in decode.frames(source_path, clip.in_, frames, fps):
            shown = frame
            if clip.crop.mode == "fixed":
                shown = decode.crop_rect(frame, clip.crop.x, clip.crop.y, clip.crop.w, clip.crop.h)
            shown = decode.resize(shown, width, height)
            brightness.append(decode.mean_brightness(shown))
            # Compared with the same tolerance the resume path uses, so a fresh render and a
            # resumed one report the same clip identically.
            tail_identical = (
                tail_identical + 1
                if previous is not None and decode.nearly_identical(shown, previous)
                else 0
            )
            previous = shown
            encoder.stdin.write(shown.tobytes())
        encoder.stdin.close()
    except BaseException:
        encoder.kill()
        encoder.wait(timeout=ENCODER_SHUTDOWN_S)
        _discard(intermediate, transforms, partial)
        raise

    if encoder.wait(timeout=ffmpeg.ENCODE_TIMEOUT_S) != 0:
        _discard(intermediate, transforms, partial)
        raise ffmpeg.FfmpegError(f"encoding {target.name} failed")

    try:
        if clip.stabilize:
            ffmpeg.stabilize(intermediate, partial, transforms)
        else:
            intermediate.replace(partial)
        partial.replace(target)
    finally:
        _discard(intermediate, transforms, partial)

    return ClipRender(
        clip=clip, path=target, frames=frames, brightness=brightness, tail_identical=tail_identical
    )


def _discard(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def run(project: Project, edl: Edl, out_dir: Path, reel: Path) -> list[ClipRender]:
    """Render every clip, then assemble and mux.

    Each clip is checkpointed: a rerun skips one whose file already exists, so an interrupted
    render resumes instead of starting over (`spec/003_pipeline.md`).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = frame_counts(edl.clips, edl.grid, edl.output.fps)

    renders: list[ClipRender] = []
    for clip, frames in zip(edl.clips, counts, strict=True):
        target = clip_path(out_dir, clip, edl.output)
        source = source_by_id(project, clip.source_id)
        if is_complete(target, frames):
            renders.append(inspect_rendered(clip, target, frames, edl.output.fps))
            continue
        renders.append(
            render_clip(
                clip,
                Path(source.path),
                target,
                frames,
                edl.output.width,
                edl.output.height,
                edl.output.fps,
            )
        )

    silent = out_dir / "concat.mp4"
    ffmpeg.concat([r.path for r in renders], silent, out_dir / "list.txt")

    track = project.music_path
    if track:
        ffmpeg.mux_music(
            silent,
            Path(track),
            reel,
            offset_s=edl.grid.first_downbeat_s,
            fade_s=FADE_S,
            duration_s=edl.grid.first_downbeat_s + edl.output.duration_s,
        )
    else:
        silent.replace(reel)

    return renders
