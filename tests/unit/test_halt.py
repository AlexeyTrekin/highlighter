"""Halt detection — the signal a clip is built backwards from.

In HEMA the referee's halt is far more detectable than the hit: after a touch both fighters
break off and reset, while the hit itself is a few frames of blur.
"""

import numpy as np
import pytest

from app.stages import candidates as stage


def signal(pattern: list[float], hz: float = 6.0) -> tuple[np.ndarray, np.ndarray]:
    stamps = np.arange(len(pattern)) / hz
    return stamps, np.array(pattern, dtype=float)


def test_a_halt_is_found_where_action_stops_and_stays_stopped():
    # Six seconds at 6 Hz: quiet, a long exchange, then a clean stop.
    pattern = [1.0] * 6 + [12.0] * 12 + [0.5] * 18
    stamps, activity = signal(pattern)

    found = stage.halts(stamps, activity)

    assert found, "the stop after an exchange must be detected"
    assert any(2.5 <= stamps[i] <= 3.5 for i in found)


def test_a_pause_inside_an_exchange_is_not_a_halt():
    """Activity dips mid-exchange all the time; only a sustained stop ends a clip."""
    pattern = [1.0] * 6 + [12.0] * 6 + [1.0] * 2 + [12.0] * 6 + [1.0] * 18
    stamps, activity = signal(pattern)

    found = stage.halts(stamps, activity)

    # The brief dip is at ~2.0s; the real stop is at ~3.3s.
    assert not any(1.8 <= stamps[i] <= 2.4 for i in found)
    assert any(stamps[i] > 3.0 for i in found)


def test_a_quiet_opening_is_not_a_halt():
    """Measured on the real footage: without this, windows ended 1.1s into a 31-second clip.

    The camera coming up and the fighters walking on is a low, drifting signal, and every
    small dip in it looked like a stop because nothing required action to have happened first.
    """
    pattern = [0.6, 0.4, 0.5, 0.3, 0.4, 0.3] + [0.5] * 12 + [12.0] * 12 + [0.5] * 12
    stamps, activity = signal(pattern)

    found = stage.halts(stamps, activity)

    assert found, "the real stop must still be found"
    assert all(stamps[i] > 2.0 for i in found), "nothing in the quiet opening is a halt"


def test_steady_activity_has_no_halt():
    stamps, activity = signal([8.0] * 40)

    assert stage.halts(stamps, activity) == []


def test_silence_has_no_halt():
    """A clip of nothing must not report a halt at every frame."""
    stamps, activity = signal([0.0] * 40)

    assert stage.halts(stamps, activity) == []


def test_too_few_samples_is_not_an_error():
    stamps, activity = signal([1.0, 2.0])

    assert stage.halts(stamps, activity) == []


def test_onset_is_where_the_action_began():
    pattern = [1.0] * 12 + [12.0] * 12 + [0.5] * 12
    stamps, activity = signal(pattern)

    halt = stage.halts(stamps, activity)[0]
    onset = stage.onset_before(stamps, activity, halt)

    assert 1.5 <= onset <= 2.6, f"onset {onset:.2f}s should sit near the rise at 2.0s"


def test_onset_never_runs_past_the_halt():
    stamps, activity = signal([5.0] * 20 + [0.2] * 20)

    halt = stage.halts(stamps, activity)[0]

    assert stage.onset_before(stamps, activity, halt) <= stamps[halt]


@pytest.mark.parametrize("level", [1.0, 50.0, 500.0])
def test_detection_is_scale_invariant(level):
    """Absolute activity varies with distance, lens and light, so the halt test is relative."""
    pattern = [0.1 * level] * 6 + [level] * 12 + [0.05 * level] * 18
    stamps, activity = signal(pattern)

    assert stage.halts(stamps, activity)
