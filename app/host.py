"""Host prerequisite checks.

The pipeline runs directly on the host with no container, so the machine's own tools are
part of the contract (`spec/004_stack.md`). Every check here answers one question a later
stage would otherwise fail on obscurely.
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass

MIN_PYTHON: tuple[int, int] = (3, 12)
STABILIZE_FILTER: str = "vidstabtransform"

# Homebrew's `ffmpeg` formula omits libvidstab; `ffmpeg-full` carries it but is keg-only, so
# its bin directory has to be put on PATH by hand. Naming the right formula here is the
# difference between a two-minute fix and installing the wrong ffmpeg twice.
FFMPEG_HINT: str = (
    "needs an ffmpeg built with libvidstab — on macOS: brew install ffmpeg-full, "
    'then export PATH="$(brew --prefix)/opt/ffmpeg-full/bin:$PATH"'
)


@dataclass(frozen=True)
class Check:
    """Result of one prerequisite check, with the fix when it failed."""

    name: str
    ok: bool
    detail: str
    hint: str = ""


def check_python() -> Check:
    found = sys.version_info[:2]
    ok = found >= MIN_PYTHON
    want = ".".join(str(p) for p in MIN_PYTHON)
    have = ".".join(str(p) for p in found)
    return Check("python", ok, f"{have} (need >= {want})")


def check_ffprobe() -> Check:
    path = shutil.which("ffprobe")
    if path is None:
        return Check("ffprobe", False, "not on PATH", FFMPEG_HINT)
    return Check("ffprobe", True, path)


def check_ffmpeg() -> Check:
    path = shutil.which("ffmpeg")
    if path is None:
        return Check("ffmpeg", False, "not on PATH", FFMPEG_HINT)
    if not has_stabilize_filter(path):
        return Check("ffmpeg", False, f"{path} lacks the {STABILIZE_FILTER} filter", FFMPEG_HINT)
    return Check("ffmpeg", True, f"{path} (libvidstab present)")


def has_stabilize_filter(ffmpeg: str = "ffmpeg") -> bool:
    """Whether this ffmpeg can stabilise, which needs libvidstab compiled in.

    Probes the filter list rather than the build configuration (`spec/004_stack.md`): a filter
    that answers here is one the renderer can actually invoke, whatever flags the build
    reports. Takes a resolved path so the answer describes the same binary the caller found.
    """
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return STABILIZE_FILTER in out.stdout


def has_ffmpeg() -> bool:
    """Whether ffmpeg and ffprobe are both callable.

    Tests marked `needs_ffmpeg` gate on this so the unit suite still runs on a bare host.
    """
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def run_checks() -> list[Check]:
    return [check_python(), check_ffmpeg(), check_ffprobe()]
