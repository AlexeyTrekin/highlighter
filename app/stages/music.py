"""Music: fit the bar grid and detect sections.

Runs before review because the bar length decides how long each clip will be, and therefore
what the user is shown and what a manual trim means (`spec/003_pipeline.md`).
"""

from pathlib import Path

import librosa

from app.audio import grid as grid_fit
from app.audio import sections as section_detect
from app.manifests.music import Music

STAGE = "music"

# How far the fitted period may sit from a least-squares fit of the beats before the grid is
# suspect. Tempo error accumulates: 1 % is half a beat across a minute, which is audible.
PERIOD_TOLERANCE: float = 0.01

# A section is "quiet" below this share of the loudest section's energy. Measured on the
# reference track, whose three major sections sit at 0.44, 1.00 and 0.66 of the peak: the
# opening has 36 % of headroom under this line and the section after it 67 % above.
QUIET_SECTION_FRACTION: float = 0.6


class GridMismatch(RuntimeError):
    """The fitted grid does not line up with the music's own structure."""


def run(track: Path) -> Music:
    y, sr = librosa.load(str(track), sr=None, mono=True)
    duration = float(len(y)) / sr

    # The drum entry anchors the grid's phase: it is a downbeat in almost any arrangement, and
    # a far better witness than onset-strength voting, which follows the backbeat.
    onset = section_detect.low_band_onset(y, sr)
    grid = grid_fit.fit(y, sr, anchor_s=onset)
    beat_times = grid_fit.beats(y, sr)
    bars = section_detect.analyse_bars(y, sr, grid, grid_fit.bar_count(grid, duration))

    music = Music(
        source="track",
        path=str(track.resolve()),
        duration_s=duration,
        grid=grid,
        sections=section_detect.build_sections(bars),
        chord_change_bars=section_detect.chord_change_bars(bars),
        bars=bars,
        backends={
            "grid": "librosa.beat_track+period_fit",
            "sections": "band_energy",
            "phase": "drum_onset" if onset is not None else "low_band_onset_vote",
            "period_error": f"{grid_fit.period_error(beat_times, grid.beat_s):.5f}",
            "beat_jitter_s": f"{grid_fit.beat_jitter(beat_times):.4f}",
        },
    )
    if onset is not None:
        music.backends["drum_onset_s"] = f"{onset:.4f}"
    return music


def drum_onset_s(music: Music) -> float | None:
    """The measured drum entry, carried through the manifest for later checks."""
    value = music.backends.get("drum_onset_s")
    return float(value) if value is not None else None


def validate_grid(music: Music) -> tuple[bool, str]:
    """Check that one tempo explains the track's own beats.

    A beat tracker reports its own confidence, not its correctness. This tests the **period**,
    which is the half that drifts: phase is anchored on the drum entry, so checking the grid
    against that same event would agree by construction and prove nothing.
    """
    recorded = music.backends.get("period_error")
    if recorded is None:
        # A measurement that was never taken is not a pass.
        return False, "no period error was recorded, so the grid is unverified"

    error = float(recorded)
    ok = error <= PERIOD_TOLERANCE
    phase = music.backends.get("phase", "unknown")
    jitter = float(music.backends.get("beat_jitter_s", 0.0))
    detail = (
        f"{music.grid.bpm:.2f} BPM is within {error * 100:.2f}% of a least-squares fit of the "
        f"tracked beats (jitter {jitter * 1000:.0f} ms); phase anchored on {phase}"
    )
    if phase != "drum_onset":
        detail += " (no drum entry found, so the phase is a vote and may follow the backbeat)"
    return ok, detail


def quiet_opening_bars(music: Music) -> int:
    """Bars of the low-energy section, or sections, the track opens with.

    Read off the section table rather than off a drum entry: a rule keyed on an instrument is a
    rule about one arrangement, and a track may have no drums, no intro, or open at full energy
    (`spec/006_music.md`). A track that starts loud simply has none of these bars, and the
    preference they carry never applies.

    On the reference track this returns the same six bars the drum entry marked — the opening
    section sits at 0.44 of the loudest section's energy and the one after it at 1.00, so the
    boundary has room on both sides.
    """
    structural = [s for s in music.sections if s.level == "major"] or music.sections
    if not structural:
        return 0

    loudest = max(s.energy for s in structural)
    if loudest <= 0:
        return 0

    bars = 0
    for section in structural:
        if section.energy > QUIET_SECTION_FRACTION * loudest:
            break
        bars = section.bar_end + 1
    return bars
