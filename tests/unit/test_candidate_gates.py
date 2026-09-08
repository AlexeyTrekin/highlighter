"""The minimum-slot gate — the fix for the freezes in the prototype's reels.

The numbers are the real ones: v42 held 3.74 s and v31 held 3.10 s, and both were given a
4.09 s slot, producing 0.35 s and 0.99 s of repeated final frame.
"""

import pytest

from app.manifests.candidates import MIN_BARS, Candidate, fits_minimum, max_bars, usable
from app.stages.candidates import apply_gates

PROTOTYPE_BAR_S = 2.0434


def candidate(end: float, start: float = 0.0) -> Candidate:
    return Candidate(id="c001", source_id="v42", start=start, end=end, anchor=end, kind="short")


@pytest.mark.parametrize(
    ("source_len", "frozen_s"),
    [(3.74, 0.35), (3.10, 0.99)],
)
def test_the_prototype_freezes_are_rejected(source_len, frozen_s):
    """Both clips that froze must now fail the gate rather than be stretched."""
    slot = MIN_BARS * PROTOTYPE_BAR_S
    assert source_len < slot
    assert frozen_s == pytest.approx(slot - source_len, abs=0.01)

    window = candidate(end=source_len)
    apply_gates(window, PROTOTYPE_BAR_S, source_len)

    assert "source_too_short" in window.flags
    assert not usable(window)


def test_a_source_that_fills_the_slot_is_kept():
    window = candidate(end=5.13)
    apply_gates(window, PROTOTYPE_BAR_S, 5.13)

    assert window.flags == []
    assert usable(window)


def test_max_bars_never_exceeds_what_the_source_holds():
    window = candidate(end=10.0)

    assert max_bars(window, PROTOTYPE_BAR_S, source_duration=10.0) == 4
    # A source shorter than the window truncates the answer.
    assert max_bars(window, PROTOTYPE_BAR_S, source_duration=5.0) == 2


def test_a_window_reaching_past_its_source_is_capped_by_the_file():
    """A window may claim an end beyond the file; only decoded footage counts."""
    window = candidate(end=8.0)

    assert not fits_minimum(window, bar_s=3.0, source_duration=3.5)


def test_gate_is_tempo_dependent():
    """The same source passes at one tempo and fails at another, so the gate must run after
    the grid is known."""
    window = candidate(end=4.5)

    apply_gates(window, bar_s=2.0, source_duration=4.5)
    assert window.flags == []

    slower = candidate(end=4.5)
    apply_gates(slower, bar_s=2.5, source_duration=4.5)
    assert "source_too_short" in slower.flags
