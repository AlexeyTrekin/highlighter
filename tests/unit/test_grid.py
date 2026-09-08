"""Grid fitting: the period must be fitted, the phase must be anchored, and the check on both
must be capable of failing."""

import numpy as np
import pytest

from app.audio import grid as grid_fit
from app.manifests.music import Grid


def regular_beats(bpm: float, count: int, start: float = 0.3) -> np.ndarray:
    return start + np.arange(count) * (60.0 / bpm)


def test_period_error_is_zero_on_a_perfect_beat_list():
    beats = regular_beats(120.0, 100)

    assert grid_fit.period_error(beats, 0.5) == pytest.approx(0.0, abs=1e-6)


def test_period_error_catches_a_wrong_tempo():
    """The prototype's 117.45 against a 120.19 track: 2.3 % out, a full beat across a minute."""
    beats = regular_beats(120.19, 120)

    error = grid_fit.period_error(beats, 60.0 / 117.45)

    assert error == pytest.approx(0.023, abs=0.002)


def test_period_error_tolerates_ordinary_jitter():
    """Beat positions wander by a frame or two even on a programmed track; a measure that
    condemns a correct grid for that is worse than no measure."""
    rng = np.random.default_rng(0)
    beats = regular_beats(120.0, 120) + rng.normal(0, 0.012, 120)

    assert grid_fit.period_error(beats, 0.5) < 0.01


def test_phase_snaps_onto_the_anchor(monkeypatch):
    beats = regular_beats(120.0, 60)
    monkeypatch.setattr(grid_fit, "beats", lambda *_: beats)

    fitted = grid_fit.fit(np.zeros(1000), 22050, anchor_s=12.196)

    assert grid_fit.alignment_error(fitted, 12.196) == pytest.approx(0.0, abs=1e-9)
    assert 0 <= fitted.first_downbeat_s < fitted.bar_s


def test_alignment_error_is_signed_and_bounded_by_half_a_bar():
    grid = Grid(bpm=120.0, beat_s=0.5, bar_s=2.0, first_downbeat_s=0.2)

    assert grid_fit.alignment_error(grid, 2.2) == pytest.approx(0.0, abs=1e-9)
    assert grid_fit.alignment_error(grid, 2.4) == pytest.approx(-0.2, abs=1e-9)
    assert grid_fit.alignment_error(grid, 2.0) == pytest.approx(0.2, abs=1e-9)
    for moment in np.arange(0.0, 20.0, 0.137):
        assert abs(grid_fit.alignment_error(grid, float(moment))) <= grid.bar_s / 2 + 1e-9


def test_bar_count_stops_at_the_end_of_the_track():
    grid = Grid(bpm=120.0, beat_s=0.5, bar_s=2.0, first_downbeat_s=0.5)

    assert grid_fit.bar_count(grid, duration_s=10.5) == 5
    assert grid_fit.bar_count(grid, duration_s=0.2) == 0


def test_beat_jitter_reports_how_steady_the_track_is():
    steady = regular_beats(120.0, 50)
    rng = np.random.default_rng(1)
    loose = steady + rng.normal(0, 0.03, 50)

    assert grid_fit.beat_jitter(steady) == pytest.approx(0.0, abs=1e-9)
    assert grid_fit.beat_jitter(loose) > grid_fit.beat_jitter(steady)


def test_too_few_beats_is_an_error_not_a_guess(monkeypatch):
    import librosa

    monkeypatch.setattr(librosa.beat, "beat_track", lambda **_: (120.0, np.array([0.5])))

    with pytest.raises(ValueError, match="too few beats"):
        grid_fit.beats(np.zeros(100), 22050)
