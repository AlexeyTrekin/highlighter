"""Motion measurement with the camera subtracted.

Camera shake in handheld footage is comparable in magnitude to fighter motion, so an
uncompensated activity signal ranks the camera operator rather than the fencing
(`spec/005_scoring.md`).
"""

import cv2
import numpy as np

# How much of the background's motion to subtract. The background moves with the camera, so
# it estimates what the camera contributed to the motion inside the boxes. Below 1.0 because
# the fighters partly occlude the background, making the outside estimate an over-read.
CAMERA_COEFFICIENT: float = 0.8

ANALYSIS_WIDTH: int = 320
ANALYSIS_HEIGHT: int = 180

Box = tuple[float, float, float, float]


def downscale(frame: np.ndarray) -> np.ndarray:
    """Grey, small, and signed — the form every motion measure here works on."""
    small = cv2.resize(frame, (ANALYSIS_WIDTH, ANALYSIS_HEIGHT))
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.int16)


def box_mask(boxes: list[Box], frame_width: int, frame_height: int) -> np.ndarray:
    """A mask over the fighters, in the downscaled frame's coordinates."""
    mask = np.zeros((ANALYSIS_HEIGHT, ANALYSIS_WIDTH), dtype=bool)
    if frame_width <= 0 or frame_height <= 0:
        return mask
    scale_x = ANALYSIS_WIDTH / frame_width
    scale_y = ANALYSIS_HEIGHT / frame_height
    for x1, y1, x2, y2 in boxes:
        left = max(0, int(x1 * scale_x))
        right = min(ANALYSIS_WIDTH, int(np.ceil(x2 * scale_x)))
        top = max(0, int(y1 * scale_y))
        bottom = min(ANALYSIS_HEIGHT, int(np.ceil(y2 * scale_y)))
        if right > left and bottom > top:
            mask[top:bottom, left:right] = True
    return mask


def split_motion(
    previous: np.ndarray, current: np.ndarray, mask: np.ndarray
) -> tuple[float, float]:
    """Mean absolute frame difference inside and outside the fighter mask."""
    difference = np.abs(current - previous)
    inside = float(difference[mask].mean()) if mask.any() else 0.0
    outside = float(difference[~mask].mean()) if (~mask).any() else 0.0
    return inside, outside


def compensate(motion_in: float, motion_out: float, k: float = CAMERA_COEFFICIENT) -> float:
    """Activity with the camera's contribution removed.

    Never negative: a frame where the background moves more than the fighters carries no
    evidence of fencing, and a negative score would rank it below a still frame for no reason.
    """
    return max(0.0, motion_in - k * motion_out)


def sharpness(frame: np.ndarray) -> float:
    """Laplacian variance — low on motion blur and on out-of-focus footage."""
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def smooth(values: np.ndarray, width: int = 3) -> np.ndarray:
    if len(values) < width or width < 2:
        return values
    return np.convolve(values, np.ones(width) / width, mode="same")
