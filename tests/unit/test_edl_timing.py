"""Cumulative frame counting — the rule that keeps every cut on the grid."""

import pytest

from app.manifests.edl import Clip, Crop, frame_counts, slot_seconds, source_seconds
from app.manifests.music import Grid


def grid(bpm: float = 120.19) -> Grid:
    beat = 60.0 / bpm
    return Grid(bpm=bpm, beat_s=beat, bar_s=4 * beat, first_downbeat_s=0.21)


def clip(bars: int, slot: int) -> Clip:
    return Clip(
        candidate_id=f"c{slot:03d}",
        source_id="v01",
        **{"in": 0.0},
        out=bars * grid().bar_s,
        bars=bars,
        grid_slot=slot,
        section="intro",
        crop=Crop(),
    )


def test_frame_counts_sum_to_the_whole_timeline():
    g = grid()
    clips = [clip(2, 0), clip(3, 2), clip(2, 5), clip(2, 7)]

    counts = frame_counts(clips, g, 30)

    assert sum(counts) == round(sum(c.bars for c in clips) * g.bar_s * 30)


def test_no_drift_accumulates_over_a_long_reel():
    """Rounding each clip alone would slide later cuts off the grid; rounding the cumulative
    boundary keeps every one of them within half a frame of its bar line."""
    g = grid()
    clips = [clip(2, i * 2) for i in range(30)]

    counts = frame_counts(clips, g, 30)

    boundary_frames = 0
    for index, count in enumerate(counts, start=1):
        boundary_frames += count
        expected_s = index * 2 * g.bar_s
        assert abs(boundary_frames / 30 - expected_s) <= 0.5 / 30


def test_per_clip_rounding_would_drift_where_cumulative_does_not():
    """Guards the reason the cumulative form exists, not just its output."""
    g = grid()
    clips = [clip(2, i * 2) for i in range(30)]

    naive_total = sum(round(c.bars * g.bar_s * 30) for c in clips)
    cumulative_total = sum(frame_counts(clips, g, 30))

    assert abs(cumulative_total - sum(c.bars for c in clips) * g.bar_s * 30) <= 0.5
    assert naive_total != cumulative_total


def test_source_seconds_carries_the_speed_factor():
    g = grid()
    fast = clip(2, 0)
    fast.speed = 0.5

    assert source_seconds(fast, g) == pytest.approx(slot_seconds(fast, g) * 0.5)


def test_fixed_crop_requires_a_rectangle():
    with pytest.raises(ValueError, match="requires x, y, w and h"):
        Crop(mode="fixed", x=0, y=0)
