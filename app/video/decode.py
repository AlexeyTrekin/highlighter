"""Frame extraction for the renderer.

Decoding is sequential from the clip's start: per-frame seeking is an order of magnitude
slower and is not permitted in the frame loop (`spec/008_render.md`).
"""

from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np


class SourceExhausted(RuntimeError):
    """A clip asked for more footage than its source holds.

    The renderer must never paper over this by repeating the last decoded frame: the repeat is
    invisible to the encoder and to every downstream check, but a viewer sees the picture stop
    dead. The director is responsible for not scheduling such a slot (`spec/005_scoring.md`),
    so this means an upstream invariant broke.
    """


def open_capture(path: Path) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {path}")
    return capture


def frames(path: Path, start_s: float, count: int, out_fps: int) -> Iterator[np.ndarray]:
    """Yield exactly `count` frames at `out_fps`, starting at `start_s`.

    Source rates vary (24 and 30 are both normal). A source frame is held across several
    output frames when the source is slower, and skipped when it is faster; the frame that is
    held is always one that was decoded.
    """
    capture = open_capture(path)
    try:
        src_fps = capture.get(cv2.CAP_PROP_FPS) or out_fps
        capture.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000.0)

        ok, current = capture.read()
        if not ok:
            raise SourceExhausted(f"{path} has no frame at {start_s:.3f}s")
        src_t = start_s

        for index in range(count):
            target_t = start_s + index / out_fps
            while src_t + 1.0 / src_fps <= target_t + 1e-6:
                ok, frame = capture.read()
                if not ok:
                    raise SourceExhausted(
                        f"{path} ran out at {src_t:.3f}s; the clip needs "
                        f"{start_s + count / out_fps:.3f}s"
                    )
                current = frame
                src_t += 1.0 / src_fps
            yield current
    finally:
        capture.release()


def resize(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_LANCZOS4)


def crop_rect(frame: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """Crop a rectangle out of a source frame.

    Only ever applied to a freshly decoded frame. Cropping a frame that was already cropped
    and upscaled produced a zoomed-in flash every fifth frame on 24 fps sources in the
    prototype, which is why the frame loop keeps the decoded frame and derives from it.
    """
    return frame[y : y + h, x : x + w]


def mean_brightness(frame: np.ndarray) -> float:
    return float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())


# Encoding and stabilisation perturb pixels slightly, so two frames that came from the same
# source frame differ by a little. This is the "same picture" threshold, not "same bytes".
IDENTICAL_TOLERANCE: float = 0.5


def nearly_identical(a: np.ndarray, b: np.ndarray) -> bool:
    """Whether two frames show the same picture after a lossy round trip."""
    if a.shape != b.shape:
        return False
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean()) < IDENTICAL_TOLERANCE
