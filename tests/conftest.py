import cv2
import numpy as np
import pytest
import soundfile

from app import host

# Which fourcc an OpenCV build can write varies by platform and wheel, so fixtures pick one
# that actually opens rather than assuming a codec is present.
CODECS = (("MJPG", ".avi"), ("avc1", ".mp4"), ("mp4v", ".mp4"))

SAMPLE_RATE = 22050


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip ffmpeg-dependent tests on a host without it, so the suite still runs bare."""
    if item.get_closest_marker("needs_ffmpeg") and not host.has_ffmpeg():
        pytest.skip("ffmpeg/ffprobe not installed on this host")


def write_video(directory, name, gray_levels, fps, size=(64, 36)):
    """A video whose Nth frame is a flat field of a known grey level."""
    width, height = size
    for fourcc, suffix in CODECS:
        path = directory / f"{name}{suffix}"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), fps, (width, height))
        if not writer.isOpened():
            writer.release()
            continue
        for level in gray_levels:
            writer.write(np.full((height, width, 3), level, dtype=np.uint8))
        writer.release()
        probe = cv2.VideoCapture(str(path))
        readable = probe.isOpened()
        probe.release()
        if readable:
            return path
    pytest.skip("this OpenCV build cannot write a video with any known fourcc")


@pytest.fixture
def video_factory():
    return write_video


@pytest.fixture
def track_factory():
    """Build a track with a known tempo and a hard drum entry partway through."""

    def build(path, bpm=120.0, bars=16, drums_from_bar=4):
        beat_s = 60.0 / bpm
        bar_s = 4 * beat_s
        total = bars * bar_s
        t = np.arange(int(total * SAMPLE_RATE)) / SAMPLE_RATE
        # A quiet pad runs throughout so the intro is not silence.
        audio = 0.05 * np.sin(2 * np.pi * 220 * t)

        drum_start = drums_from_bar * bar_s
        for beat in range(int(total / beat_s)):
            onset = beat * beat_s
            if onset < drum_start:
                continue
            index = int(onset * SAMPLE_RATE)
            length = int(0.12 * SAMPLE_RATE)
            envelope = np.exp(-np.linspace(0, 12, length))
            kick = 0.9 * np.sin(2 * np.pi * 55 * np.arange(length) / SAMPLE_RATE) * envelope
            audio[index : index + length] += kick[: max(0, len(audio) - index)]

        soundfile.write(path, audio, SAMPLE_RATE)
        return path

    return build
