"""Frame extraction: exact counts, honest frame-rate conversion, and no silent freezing."""

import cv2
import numpy as np
import pytest

from app.video import decode

WIDTH, HEIGHT = 64, 36

# Which fourcc an OpenCV build can write varies by platform and wheel, so the fixture picks
# one that actually opens rather than assuming a codec is present.
CODECS = (("MJPG", ".avi"), ("avc1", ".mp4"), ("mp4v", ".mp4"))


def write_video(directory, name, gray_levels, fps):
    """A video whose Nth frame is a flat field of a known grey level."""
    for fourcc, suffix in CODECS:
        path = directory / f"{name}{suffix}"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), fps, (WIDTH, HEIGHT))
        if not writer.isOpened():
            writer.release()
            continue
        for level in gray_levels:
            writer.write(np.full((HEIGHT, WIDTH, 3), level, dtype=np.uint8))
        writer.release()
        probe = cv2.VideoCapture(str(path))
        readable = probe.isOpened()
        probe.release()
        if readable:
            return path
    pytest.skip("this OpenCV build cannot write a video with any known fourcc")


def test_yields_exactly_the_requested_frame_count(tmp_path):
    source = write_video(tmp_path, "src", list(range(20, 140, 4)), fps=30)

    frames = list(decode.frames(source, start_s=0.0, count=12, out_fps=30))

    assert len(frames) == 12


def test_running_past_the_source_raises_rather_than_repeating(tmp_path):
    """The prototype repeated its last decoded frame here, which a viewer sees as a freeze
    and no downstream check can detect."""
    source = write_video(tmp_path, "short", [50] * 10, fps=30)

    with pytest.raises(decode.SourceExhausted):
        list(decode.frames(source, start_s=0.0, count=60, out_fps=30))


def test_24_to_30_conversion_only_repeats_decoded_frames(tmp_path):
    """Converting 24 fps to 30 duplicates source frames; every emitted frame must be one that
    was actually decoded, never a re-derived one."""
    levels = list(range(30, 150, 5))
    source = write_video(tmp_path, "f24", levels, fps=24)

    frames = list(decode.frames(source, start_s=0.0, count=20, out_fps=30))
    emitted = [decode.mean_brightness(f) for f in frames]

    for value in emitted:
        assert min(abs(value - level) for level in levels) < 6

    # Duplication must hold a frame, never jump backwards.
    for previous, current in zip(emitted, emitted[1:], strict=False):
        assert current >= previous - 6


def test_conversion_holds_frames_rather_than_dropping_them(tmp_path):
    source = write_video(tmp_path, "f24", list(range(30, 150, 5)), fps=24)

    frames = list(decode.frames(source, start_s=0.0, count=20, out_fps=30))
    levels = [round(decode.mean_brightness(f)) for f in frames]

    assert len(set(levels)) < len(levels), "30 fps from 24 fps must repeat some frames"


@pytest.mark.parametrize("start_s", [0.0, 1.0, 2.5, 3.333])
def test_seeking_lands_within_a_frame_of_the_requested_moment(tmp_path, start_s):
    """Clip starts come from a timestamp seek, so a backend that snapped to keyframes instead
    would misplace every clip by up to a GOP without any other check noticing."""
    levels = [10 + i for i in range(150)]
    source = write_video(tmp_path, "ramp", levels, fps=30)

    first = next(iter(decode.frames(source, start_s=start_s, count=1, out_fps=30)))

    expected = 10 + round(start_s * 30)
    assert abs(decode.mean_brightness(first) - expected) <= 2


def test_nearly_identical_tolerates_a_lossy_round_trip():
    frame = np.full((HEIGHT, WIDTH, 3), 120, dtype=np.uint8)
    jittered = frame.copy()
    jittered[0, 0] = 121

    assert decode.nearly_identical(frame, jittered)
    assert not decode.nearly_identical(frame, np.full_like(frame, 130))


def test_crop_is_taken_from_the_frame_it_was_given(tmp_path):
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    frame[10:20, 10:20] = 200

    cropped = decode.crop_rect(frame, 10, 10, 10, 10)

    assert cropped.shape == (10, 10, 3)
    assert decode.mean_brightness(cropped) == pytest.approx(200, abs=1)
