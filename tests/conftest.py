import pytest

from app import host


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip ffmpeg-dependent tests on a host without it, so the suite still runs bare."""
    if item.get_closest_marker("needs_ffmpeg") and not host.has_ffmpeg():
        pytest.skip("ffmpeg/ffprobe not installed on this host")
