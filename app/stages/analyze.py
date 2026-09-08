"""Analyze: decode each source once and record what every later stage needs.

The only stage that performs a full decode, so it shards per source and is resumable at that
granularity (`spec/003_pipeline.md`). Everything downstream reads `analysis/vNN.json` instead
of touching video again.
"""

from collections.abc import Iterator
from pathlib import Path

import cv2

from app.manifests.analysis import Analysis, Row
from app.manifests.project import Source
from app.video import detect, motion

STAGE = "analyze"

# Every 5th frame is ~6 Hz on 30 fps material. Fine enough to place a halt within a couple of
# frames, coarse enough that fifty clips analyse in minutes rather than an hour.
SAMPLE_STEP: int = 5

# How far short of the container's duration a decode may stop before it counts as truncated.
# Sampling every Nth frame plus a container duration rounded to the nearest frame leaves a
# legitimate gap of well under a second.
TRUNCATION_TOLERANCE_S: float = 1.0


class TruncatedDecode(RuntimeError):
    """Decoding ended well before the end of the file."""


def analysis_path(root: Path, source_id: str) -> Path:
    return root / "analysis" / f"{source_id}.json"


def sampled_frames(path: Path, step: int) -> Iterator[tuple[int, "cv2.typing.MatLike"]]:
    """Yield every `step`-th frame, decoding sequentially.

    `grab` skips the frames in between without paying for their colour conversion, which is
    most of the cost of decoding a frame that is about to be discarded.
    """
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {path}")
    try:
        index = 0
        while True:
            if not capture.grab():
                return
            if index % step == 0:
                ok, frame = capture.retrieve()
                if not ok:
                    return
                yield index, frame
            index += 1
    finally:
        capture.release()


def analyse(source: Source, step: int = SAMPLE_STEP) -> Analysis:
    """Detect fighters and measure motion across one source."""
    path = Path(source.path)
    fps = source.fps or 30.0

    rows: list[Row] = []
    previous_small = None
    previous_boxes: list[detect.Box] = []
    frame_count = 0

    for index, frame in sampled_frames(path, step):
        frame_count = index + 1
        # Measured on the decoded frame, not on the container's reported size. OpenCV applies
        # rotation metadata, so a portrait clip stored as landscape decodes transposed — and
        # the fighter test is a fraction of frame *height*, which would then be measured
        # against the wrong side and promote spectators into the pair.
        height, width = frame.shape[:2]
        small = motion.downscale(frame)
        seen = detect.fighters(detect.detect_people(frame), height)
        boxes = detect.track(previous_boxes, seen)

        if previous_small is None:
            motion_in = motion_out = 0.0
        else:
            mask = motion.box_mask(boxes, width, height)
            motion_in, motion_out = motion.split_motion(previous_small, small, mask)

        rows.append(
            Row(
                t=index / fps,
                boxes=boxes,
                kits=[detect.kit_colours(frame, box) for box in boxes],
                motion_in=motion_in,
                motion_out=motion_out,
                activity=motion.compensate(motion_in, motion_out),
                gap=detect.normalised_gap(boxes),
                sharpness=motion.sharpness(frame),
                brightness=float(small.mean()),
            )
        )
        previous_small = small
        previous_boxes = boxes

    if rows and source.duration_s - rows[-1].t > TRUNCATION_TOLERANCE_S:
        # A decode that stops early produces a perfectly well-formed manifest covering part of
        # the file, and the resume path then skips that source forever because the file exists.
        # Loud here, or wrong everywhere downstream.
        raise TruncatedDecode(
            f"{path.name}: decoding stopped at {rows[-1].t:.1f}s of {source.duration_s:.1f}s"
        )

    return Analysis(
        source_id=source.id,
        fps=fps,
        frame_count=frame_count,
        width=source.width,
        height=source.height,
        duration_s=source.duration_s,
        sample_step=step,
        rows=rows,
    )
