"""Beat grid fitting.

Fit the period from the beat list; never take a reported tempo and never round it
(`spec/006_music.md`). A tempo 2 % wrong drifts a full beat across a minute, which puts every
later cut off the music.
"""

import librosa
import numpy as np

from app.manifests.music import Grid

BEATS_PER_BAR: int = 4
LOW_BAND_HZ: float = 200.0
LOW_BAND_MELS: int = 16


def fit(
    y: np.ndarray, sr: int, anchor_s: float | None = None, beats_per_bar: int = BEATS_PER_BAR
) -> Grid:
    """Derive the bar grid from audio.

    `anchor_s` is a moment known to fall on a downbeat — the drum entry, in practice. Given
    one, the phase is snapped to it, because scoring candidate phases by onset strength picks
    the backbeat on any track whose snare is louder than its kick, which is most rock.
    """
    beat_times = beats(y, sr)
    beat_s = float(np.median(np.diff(beat_times)))
    bar_s = beats_per_bar * beat_s

    if anchor_s is not None:
        first_downbeat = float(anchor_s % bar_s)
    else:
        first_downbeat = _phase_by_onset(y, sr, beat_times, beats_per_bar)

    return Grid(
        bpm=60.0 / beat_s,
        beat_s=beat_s,
        bar_s=bar_s,
        first_downbeat_s=first_downbeat,
        beats_per_bar=beats_per_bar,
    )


def beats(y: np.ndarray, sr: int) -> np.ndarray:
    _, beat_times = librosa.beat.beat_track(y=y, sr=sr, units="time")
    if len(beat_times) < 2:
        raise ValueError("beat tracking found too few beats to fit a period")
    return beat_times


def _phase_by_onset(y: np.ndarray, sr: int, beat_times: np.ndarray, beats_per_bar: int) -> float:
    """Fallback phase: the candidate whose bar starts carry the most low-band onset energy.

    Weaker than an anchor and known to be fooled by a loud backbeat, so `validate_grid`
    reports when the grid rests on it.
    """
    mel = librosa.feature.melspectrogram(y=y, sr=sr, fmax=LOW_BAND_HZ, n_mels=LOW_BAND_MELS)
    strength = librosa.onset.onset_strength(S=librosa.power_to_db(mel), sr=sr)
    times = librosa.times_like(strength, sr=sr)
    scores = [
        float(np.mean(np.interp(beat_times[phase::beats_per_bar], times, strength)))
        for phase in range(beats_per_bar)
    ]
    return float(beat_times[int(np.argmax(scores))])


def period_error(beat_times: np.ndarray, beat_s: float) -> float:
    """Relative disagreement between the fitted period and a least-squares fit of the beats.

    Tests the period rather than the phase, which is the half that drifts: a tempo 2 % wrong
    slides a full beat across a minute.

    Deliberately not the distance from each beat to a rigid grid. Beat positions wander by a
    frame or two even on a programmed track, and that wander accumulates into a residual of
    100 ms or more while the tempo itself is exact — a measure that condemns a correct grid is
    worse than no measure.
    """
    if len(beat_times) < 3:
        return 0.0
    slope = float(np.polyfit(np.arange(len(beat_times)), beat_times, 1)[0])
    return abs(beat_s - slope) / slope if slope else 0.0


def beat_jitter(beat_times: np.ndarray) -> float:
    """Standard deviation of the tracked beat intervals — how steady the track itself is."""
    return float(np.std(np.diff(beat_times))) if len(beat_times) > 2 else 0.0


def bar_count(grid: Grid, duration_s: float) -> int:
    """Whole bars between the first downbeat and the end of the track."""
    return max(0, int((duration_s - grid.first_downbeat_s) / grid.bar_s))


def alignment_error(grid: Grid, event_s: float) -> float:
    """Signed distance from `event_s` to the nearest bar line."""
    bars = (event_s - grid.first_downbeat_s) / grid.bar_s
    return (round(bars) - bars) * grid.bar_s
