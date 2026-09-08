"""Window proposal: what gets offered to the director, and what gets dropped with a reason.

Four of this stage's defects lived here and none had a direct test — the integration suite
only asserted that whatever came out was contiguous.
"""

import numpy as np
import pytest

from app.manifests.analysis import Analysis, Row
from app.manifests.candidates import Candidate
from app.manifests.project import Source
from app.stages import candidates as stage

BAR_S = 2.0
HZ = 6.0


def analysis(rows: list[Row], duration: float) -> Analysis:
    return Analysis(
        source_id="v01",
        fps=30.0,
        frame_count=int(duration * 30),
        width=1280,
        height=720,
        duration_s=duration,
        sample_step=5,
        rows=rows,
    )


def exchange_rows(quiet: int, busy: int, tail: int) -> list[Row]:
    """Quiet, then an exchange that closes to measure, then a settled reset."""
    rows = []
    for _ in range(quiet):
        rows.append(Row(t=len(rows) / HZ, boxes=_pair(1.5), activity=1.0, gap=1.5))
    for index in range(busy):
        gap = 1.4 if index % 2 else 0.3
        rows.append(Row(t=len(rows) / HZ, boxes=_pair(gap), activity=14.0, gap=gap))
    for _ in range(tail):
        rows.append(Row(t=len(rows) / HZ, boxes=_pair(1.6), activity=0.8, gap=1.6))
    return rows


def _pair(gap: float) -> list[tuple[float, float, float, float]]:
    return [(0.0, 100.0, 200.0, 500.0), (200.0 + gap * 400, 100.0, 400.0 + gap * 400, 500.0)]


def source_of(duration: float, shape: str = "long") -> Source:
    return Source(
        id="v01",
        original_name="v01.mp4",
        path="/tmp/v01.mp4",
        duration_s=duration,
        fps=30.0,
        width=1280,
        height=720,
        shape=shape,  # type: ignore[arg-type]
    )


def test_an_exchange_yields_a_window_anchored_after_the_halt():
    rows = exchange_rows(quiet=12, busy=18, tail=18)
    data = analysis(rows, duration=len(rows) / HZ)

    found = stage.windows(source_of(len(rows) / HZ), data, BAR_S)

    halt_windows = [w for w in found if w.origin == "halt"]
    assert halt_windows
    assert 4.5 <= halt_windows[0].anchor <= 6.5


def test_a_short_source_falls_back_when_its_only_halt_is_unusable():
    """Recordings open mid-action, so the only halt can sit too early to cut from. Losing the
    clip to that costs the exchange at its end, which for a short source is the whole point."""
    rows = exchange_rows(quiet=1, busy=4, tail=30)
    data = analysis(rows, duration=len(rows) / HZ)

    found = stage.windows(source_of(len(rows) / HZ, shape="short"), data, BAR_S)

    assert any(w.origin == "fallback" for w in found), "the tail must still be proposed"


def test_windows_that_cannot_be_cut_are_still_recorded():
    rows = exchange_rows(quiet=1, busy=4, tail=30)
    data = analysis(rows, duration=len(rows) / HZ)

    found = stage.windows(source_of(len(rows) / HZ, shape="short"), data, BAR_S)

    assert any(w.end < stage.OPENING_MIN_BARS * BAR_S for w in found)


def test_a_calm_window_never_overlaps_a_chosen_exchange():
    """The gap holds steady during the reset right after a halt, which is exactly where a
    stable stretch is easiest to find — and both clips would show the same seconds."""
    rows = exchange_rows(quiet=12, busy=18, tail=30)
    data = analysis(rows, duration=len(rows) / HZ)

    found = stage.windows(source_of(len(rows) / HZ), data, BAR_S)

    halts = [w for w in found if w.origin == "halt"]
    calms = [w for w in found if w.origin == "calm"]
    for calm in calms:
        assert not any(calm.start < h.end and h.start < calm.end for h in halts)


def test_a_stable_stretch_is_taken_as_long_as_it_holds():
    """A clip reaches back the length of its slot, so a window shorter than the slot would put
    unexamined footage on screen."""
    rows = [Row(t=i / HZ, boxes=_pair(1.4), activity=2.0, gap=1.4) for i in range(60)]
    data = analysis(rows, duration=len(rows) / HZ)

    found = stage.stable_windows(source_of(len(rows) / HZ), data, BAR_S)

    assert found
    assert found[0].end - found[0].start >= 2 * BAR_S


def test_a_swinging_gap_is_not_a_stable_window():
    rows = exchange_rows(quiet=0, busy=40, tail=0)
    data = analysis(rows, duration=len(rows) / HZ)

    assert stage.stable_windows(source_of(len(rows) / HZ), data, BAR_S) == []


def test_empty_frames_are_not_a_walk_on():
    """The intro orders by fewest fighters on camera, so counting a camera-on-the-floor
    stretch as one person would open the reel on nothing."""
    rows = [Row(t=i / HZ, boxes=[], activity=0.5) for i in range(40)]
    data = analysis(rows, duration=len(rows) / HZ)

    assert stage.solo_windows(source_of(len(rows) / HZ), data, BAR_S) == []


def test_one_fighter_on_camera_is_a_walk_on():
    rows = [
        Row(t=i / HZ, boxes=[(0.0, 100.0, 200.0, 500.0)] if 6 <= i < 36 else [], activity=1.0)
        for i in range(40)
    ]
    data = analysis(rows, duration=len(rows) / HZ)

    found = stage.solo_windows(source_of(len(rows) / HZ), data, BAR_S)

    assert len(found) == 1
    assert found[0].origin == "calm"


def test_the_visibility_gate_applies_to_exchanges_but_not_walk_ons():
    """An exchange is worthless without both fighters; a walk-on with one person is exactly
    what the drumless intro wants."""
    rows = [Row(t=i / HZ, boxes=[], activity=1.0, brightness=100.0) for i in range(30)]
    data = analysis(rows, duration=5.0)

    exchange = Candidate(
        id="c001", source_id="v01", start=0.0, end=4.5, anchor=4.5, kind="short", origin="halt"
    )
    walk_on = Candidate(
        id="c002", source_id="v01", start=0.0, end=4.5, anchor=4.5, kind="short", origin="calm"
    )
    stage.apply_gates(exchange, data, BAR_S, 5.0)
    stage.apply_gates(walk_on, data, BAR_S, 5.0)

    assert "fighters_not_both_visible" in exchange.flags
    assert "fighters_not_both_visible" not in walk_on.flags


def test_a_pan_into_bright_sky_is_not_a_scene_cut():
    """Measured on the real footage in WAL 1.1: +17.7 then +14.3 per frame, and these samples
    are five frames apart. A naive per-sample threshold deletes ordinary footage — and here it
    would be a hard drop, not a warning."""
    levels = [92.9, 110.0, 127.7, 142.0, 155.0, 165.0, 170.2, 171.0]
    rows = [Row(t=i / HZ, brightness=level) for i, level in enumerate(levels)]
    data = analysis(rows, duration=len(rows) / HZ)

    assert not stage.scene_cut_inside(data, 0.0, len(rows) / HZ)


def test_a_persistent_brightness_step_is_a_scene_cut():
    levels = [100.0, 101.0, 99.0, 100.0, 40.0, 41.0, 39.0, 40.0]
    rows = [Row(t=i / HZ, brightness=level) for i, level in enumerate(levels)]
    data = analysis(rows, duration=len(rows) / HZ)

    assert stage.scene_cut_inside(data, 0.0, len(rows) / HZ)


def test_a_clip_that_ends_mid_exchange_has_no_halt():
    """Without room for the settling period, the last samples of a truncated recording read as
    a stop — and the smoother's zero-padded edge makes that final sample look quieter still."""
    stamps = np.arange(20) / HZ
    activity = np.array([1.0] * 6 + [12.0] * 13 + [4.0])

    found = stage.halts(stamps, activity)

    assert all(stamps[-1] - stamps[i] >= stage.SETTLE_S for i in found)


@pytest.mark.parametrize("shape", ["short", "long"])
def test_no_proposed_window_starts_after_it_ends(shape):
    rows = exchange_rows(quiet=12, busy=18, tail=18)
    data = analysis(rows, duration=len(rows) / HZ)

    for window in stage.windows(source_of(len(rows) / HZ, shape=shape), data, BAR_S):
        assert window.start <= window.end
        assert window.anchor <= window.end
