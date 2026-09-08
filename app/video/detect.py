"""Person detection with YOLOv8n through ONNX Runtime.

CPU only and no PyTorch: the detector is the one heavy model in the baseline, and keeping it
in ONNX is what lets `spec/004_stack.md` exclude the torch tree from the base install.
"""

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
import onnxruntime as ort

from app import assets

INPUT_SIZE: int = 640
PERSON_CLASS: int = 0
CONFIDENCE: float = 0.35
NMS_IOU: float = 0.5

# A fighter fills a good part of the frame; spectators and bystanders do not. Measured as a
# fraction of frame height so it survives any resolution (`spec/005_scoring.md`).
FIGHTER_MIN_HEIGHT_FRAC: float = 0.22
# The two fighters stand at much the same distance from the camera, so they appear much the
# same height. A spectator does not. Without this, whenever one fighter leaves frame the next
# tallest bystander is promoted into the pair and "both fighters visible" is always true —
# which makes the measure useless exactly when it matters.
FIGHTER_HEIGHT_RATIO: float = 0.6
FIGHTERS: int = 2

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Letterbox:
    """How a frame was fitted into the square input, so boxes can be mapped back.

    The frame is scaled to fit and padded rather than stretched: squashing 16:9 into a square
    distorts people vertically, and box height is exactly what decides who is a fighter.
    """

    scale: float
    pad_x: float
    pad_y: float

    def to_source(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.pad_x) / self.scale, (y - self.pad_y) / self.scale


@lru_cache(maxsize=1)
def session() -> ort.InferenceSession:
    """The loaded model, kept for the life of the process.

    Loading costs far more than an inference, and analysis runs it thousands of times.
    """
    return ort.InferenceSession(
        str(assets.require(assets.YOLOV8N)), providers=["CPUExecutionProvider"]
    )


def letterbox(frame: np.ndarray, size: int = INPUT_SIZE) -> tuple[np.ndarray, Letterbox]:
    height, width = frame.shape[:2]
    scale = min(size / width, size / height)
    new_w, new_h = round(width * scale), round(height * scale)
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    return canvas, Letterbox(scale=scale, pad_x=pad_x, pad_y=pad_y)


def detect_people(frame: np.ndarray) -> list[tuple[Box, float]]:
    """Person boxes as `([x1, y1, x2, y2], confidence)` in source-frame pixels."""
    canvas, transform = letterbox(frame)
    blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0

    model = session()
    raw = model.run(None, {model.get_inputs()[0].name: blob})[0][0].T

    scores = raw[:, 4 + PERSON_CLASS]
    keep = scores > CONFIDENCE
    if not keep.any():
        return []

    centres = raw[keep, :4]
    confidences = scores[keep]

    half_w, half_h = centres[:, 2] / 2, centres[:, 3] / 2
    corners = np.stack(
        [
            centres[:, 0] - half_w,
            centres[:, 1] - half_h,
            centres[:, 0] + half_w,
            centres[:, 1] + half_h,
        ],
        axis=1,
    )

    chosen = cv2.dnn.NMSBoxes(
        np.stack([corners[:, 0], corners[:, 1], centres[:, 2], centres[:, 3]], axis=1).tolist(),
        confidences.tolist(),
        CONFIDENCE,
        NMS_IOU,
    )
    if len(chosen) == 0:
        return []

    found: list[tuple[Box, float]] = []
    for index in np.array(chosen).reshape(-1):
        x1, y1 = transform.to_source(corners[index, 0], corners[index, 1])
        x2, y2 = transform.to_source(corners[index, 2], corners[index, 3])
        found.append(((float(x1), float(y1), float(x2), float(y2)), float(confidences[index])))
    return found


def fighters(people: list[tuple[Box, float]], frame_height: int) -> list[Box]:
    """The fighters, ordered left to right — one of them, or two, or none.

    Two tests, not one: big enough in the frame, and comparable in height to the largest
    person found. A bystander can clear an absolute height threshold on a wide shot, and
    promoting one into the pair would report both fighters present while one is off camera.
    """
    tall = [box for box, _ in people if (box[3] - box[1]) >= FIGHTER_MIN_HEIGHT_FRAC * frame_height]
    if not tall:
        return []

    tall.sort(key=lambda b: -(b[3] - b[1]))
    largest = tall[0][3] - tall[0][1]
    peers = [b for b in tall[:FIGHTERS] if (b[3] - b[1]) >= FIGHTER_HEIGHT_RATIO * largest]
    return sorted(peers, key=lambda b: b[0])


def track(previous: list[Box], current: list[Box]) -> list[Box]:
    """Keep left/right identity across frames.

    Fighters cross, and when they do the left-to-right ordering swaps who is who. Taking the
    cheaper of the two assignments keeps a fighter's box attached to the same fighter, which
    is what makes per-fighter motion and kit colour mean anything over time.
    """
    if len(previous) != FIGHTERS or len(current) != FIGHTERS:
        return current

    def centre(box: Box) -> float:
        return (box[0] + box[2]) / 2

    straight = abs(centre(current[0]) - centre(previous[0])) + abs(
        centre(current[1]) - centre(previous[1])
    )
    crossed = abs(centre(current[0]) - centre(previous[1])) + abs(
        centre(current[1]) - centre(previous[0])
    )
    return current[::-1] if crossed < straight else current


def normalised_gap(boxes: list[Box]) -> float | None:
    """Distance between fighters in body-heights, or None when both are not visible.

    Normalising by height makes the measure invariant to pan and zoom, so a gap threshold
    means the same thing on a close shot and a wide one.
    """
    if len(boxes) != FIGHTERS:
        return None
    left, right = boxes
    height = ((left[3] - left[1]) + (right[3] - right[1])) / 2
    if height <= 0:
        return None
    centres = abs((right[0] + right[2]) / 2 - (left[0] + left[2]) / 2)
    half_widths = ((left[2] - left[0]) + (right[2] - right[0])) / 2
    return float((centres - half_widths) / height)


def kit_colours(frame: np.ndarray, box: Box) -> list[float] | None:
    """Median HSV of a jacket band and a trouser band.

    Kit colour is what identifies a fighter across bouts — faces are behind masks
    (`spec/005_scoring.md`). Collected here because the frame is already decoded; it is used
    by target identification in a later step.
    """
    x1, y1, x2, y2 = (int(v) for v in box)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
    height = y2 - y1
    if height < 20 or x2 <= x1:
        return None

    bands = (
        frame[y1 + int(height * 0.15) : y1 + int(height * 0.50), x1:x2],
        frame[y1 + int(height * 0.55) : y1 + int(height * 0.90), x1:x2],
    )
    values: list[float] = []
    for band in bands:
        if band.size == 0:
            return None
        hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(float)
        values += [float(v) for v in np.median(hsv, axis=0)]
    return values
