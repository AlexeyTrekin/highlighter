"""Thin wrappers over the host's ffmpeg and ffprobe.

Every call passes an argument list and a timeout, never a shell string
(`instructions/lang/python.md`).
"""

import json
import subprocess
from pathlib import Path

PROBE_TIMEOUT_S: int = 60
ENCODE_TIMEOUT_S: int = 3600


class FfmpegError(RuntimeError):
    """An ffmpeg or ffprobe invocation failed."""


def probe(path: Path) -> dict:
    """Container and stream metadata for a media file."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        raise FfmpegError(f"ffprobe failed on {path}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def video_stream(info: dict) -> dict:
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    raise FfmpegError("file has no video stream")


def frame_rate(stream: dict) -> float:
    numerator, _, denominator = stream.get("r_frame_rate", "0/1").partition("/")
    den = float(denominator or 1)
    return float(numerator) / den if den else 0.0


def duration_s(info: dict) -> float:
    return float(info["format"]["duration"])


def run(args: list[str], *, timeout: int = ENCODE_TIMEOUT_S) -> None:
    """Run ffmpeg, raising with its stderr when it fails."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-y", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise FfmpegError(f"ffmpeg failed: {result.stderr.strip()[-2000:]}")


def stabilize(source: Path, target: Path, transforms: Path) -> None:
    """Two-pass libvidstab, applied after any crop (`spec/008_render.md`).

    The smoothing values are a ceiling: heavier settings crop the fighters out of frame.
    """
    run(
        [
            "-i",
            str(source),
            "-vf",
            f"vidstabdetect=shakiness=5:accuracy=15:result={transforms}",
            "-f",
            "null",
            "-",
        ]
    )
    run(
        [
            "-i",
            str(source),
            "-vf",
            f"vidstabtransform=input={transforms}:smoothing=10:zoom=2:optzoom=0:interpol=bicubic"
            ",unsharp=3:3:0.4",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ]
    )


def concat(clips: list[Path], target: Path, list_file: Path) -> None:
    """Join rendered clips by stream copy.

    The copy is an optimisation guarded by every boundary being a hard cut; a transition would
    need a filter graph spanning two clips (`spec/008_render.md`).
    """
    list_file.write_text("".join(f"file '{clip.resolve()}'\n" for clip in clips), encoding="utf-8")
    run(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(target),
        ]
    )


def mux_music(
    video: Path, track: Path, target: Path, *, offset_s: float, fade_s: float, duration_s: float
) -> None:
    """Lay the track under the reel, offsetting video so cuts meet the first downbeat.

    The lead-in is black rather than a held first frame: cloning would open the reel on a
    still picture, which reads as exactly the freeze this pipeline exists to avoid. The
    fade-in covers it.
    """
    fade_start = max(0.0, duration_s - fade_s)
    run(
        [
            "-i",
            str(video),
            "-i",
            str(track),
            "-filter_complex",
            f"[0:v]tpad=start_duration={offset_s:.6f}:start_mode=add:color=black,"
            f"fade=t=in:st=0:d=0.5,fade=t=out:st={fade_start:.3f}:d={fade_s:.3f}[v];"
            f"[1:a]atrim=0:{duration_s:.3f},"
            f"afade=t=out:st={fade_start:.3f}:d={fade_s:.3f}[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-t",
            f"{duration_s:.3f}",
            str(target),
        ]
    )
