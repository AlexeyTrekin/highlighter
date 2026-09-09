"""Per-bar band energies and hierarchical section detection.

One threshold finds only the loudest transition. On the reference track the sub-150 Hz band
steps x1.7 as subtle drums enter and x43 as the kit arrives; a listener hears both, so
boundaries are detected at two sensitivities and all of them are kept
(`spec/006_music.md`).
"""

import librosa
import numpy as np

from app.manifests.music import Bar, Grid, Section

LOW_HZ: float = 150.0
HIGH_HZ: float = 4000.0
HOP: int = 512
N_FFT: int = 2048

# A band-energy ratio between neighbouring bars. The major threshold catches a part change;
# the minor one catches a step inside a part that the major threshold is deaf to. Drums
# arriving is a far bigger jump than drums leaving — a kit entering is x40 while a fade-out is
# nearer x2.5 — so the major threshold has to sit low enough to hear the quieter of the two.
MAJOR_RATIO: float = 2.5
MINOR_RATIO: float = 1.5
CHROMA_TOP_K: int = 3

# A major section shorter than this cannot hold even the shortest clip, so a boundary that
# would carve one out is demoted rather than fragmenting the timeline.
MIN_MAJOR_BARS: int = 2

# The onset detector's threshold: how far above the quiet level counts as the drums arriving.
ONSET_RISE_FRACTION: float = 0.25

# Finer hop for locating the drum entry, which is compared against a bar line and so needs
# better resolution than the bar-level analysis provides.
ONSET_HOP: int = 256
ONSET_WINDOW_S: float = 1.0


def analyse_bars(y: np.ndarray, sr: int, grid: Grid, bar_count: int) -> list[Bar]:
    """Per-bar RMS, band energies and dominant pitch classes."""
    spectrum = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    times = librosa.times_like(spectrum, sr=sr, hop_length=HOP, n_fft=N_FFT)
    chroma = librosa.feature.chroma_stft(S=spectrum, sr=sr)

    low_band = spectrum[freqs < LOW_HZ].mean(axis=0)
    high_band = spectrum[freqs > HIGH_HZ].mean(axis=0)
    rms = spectrum.mean(axis=0)

    bars: list[Bar] = []
    for index in range(bar_count):
        start = grid.first_downbeat_s + index * grid.bar_s
        window = (times >= start) & (times < start + grid.bar_s)
        if not window.any():
            continue
        top = np.argsort(-chroma[:, window].mean(axis=1))[:CHROMA_TOP_K]
        bars.append(
            Bar(
                index=index,
                t=float(start),
                rms=float(rms[window].mean()),
                low_energy=float(low_band[window].mean()),
                high_energy=float(high_band[window].mean()),
                chroma_top=[int(p) for p in top],
            )
        )
    return bars


def boundary_bars(bars: list[Bar]) -> dict[int, str]:
    """Bar indices where the music changes, each tagged `major` or `minor`.

    A bar qualifies on the ratio of its low-band energy to the previous bar's, in either
    direction — drums arriving and drums leaving are both boundaries.
    """
    found: dict[int, str] = {}
    for previous, current in zip(bars, bars[1:], strict=False):
        if previous.low_energy <= 1e-9:
            continue
        ratio = current.low_energy / previous.low_energy
        swing = max(ratio, 1.0 / ratio) if ratio > 0 else 0.0
        if swing >= MAJOR_RATIO:
            found[current.index] = "major"
        elif swing >= MINOR_RATIO:
            found[current.index] = "minor"
    return found


def chord_change_bars(bars: list[Bar]) -> list[int]:
    """Bars whose dominant pitch classes differ from the previous bar's."""
    changes: list[int] = []
    for previous, current in zip(bars, bars[1:], strict=False):
        if set(previous.chroma_top) != set(current.chroma_top):
            changes.append(current.index)
    return changes


def build_sections(bars: list[Bar]) -> list[Section]:
    """Turn boundaries into sections, positionally named.

    Names are positional (`intro`, `s1`, ..., `outro`) because a functional label the baseline
    cannot actually determine would be a guess; a positional label is honest and the director
    keys off `energy` anyway (`spec/006_music.md`).
    """
    if not bars:
        return []

    boundaries = boundary_bars(bars)
    major_starts = _drop_short_spans(
        sorted({bars[0].index} | {b for b, lvl in boundaries.items() if lvl == "major"}),
        last_bar=bars[-1].index,
    )
    sections = _spans(bars, major_starts, "major")
    minor_starts = sorted(b for b, lvl in boundaries.items() if lvl == "minor")
    sections += _nested_minor_spans(bars, sections, minor_starts)
    return sorted(sections, key=lambda s: (s.bar_start, s.level == "minor"))


def _drop_short_spans(starts: list[int], last_bar: int) -> list[int]:
    """Keep only boundaries that leave a section long enough to hold a clip.

    A fade-out often reads as two steps a bar apart; taking both would carve out a one-bar
    section no clip can fill, and the director would then have nowhere to put the coda.
    """
    kept = [starts[0]]
    for start in starts[1:]:
        if start - kept[-1] >= MIN_MAJOR_BARS:
            kept.append(start)
    if len(kept) > 1 and last_bar - kept[-1] + 1 < MIN_MAJOR_BARS:
        kept.pop()
    return kept


def _spans(bars: list[Bar], starts: list[int], level: str) -> list[Section]:
    last = bars[-1].index
    spans: list[Section] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] - 1 if position + 1 < len(starts) else last
        spans.append(
            Section(
                name=_positional_name(position, len(starts)),
                level=level,  # type: ignore[arg-type]
                bar_start=start,
                bar_end=end,
                energy=_mean_energy(bars, start, end),
            )
        )
    return spans


def _nested_minor_spans(
    bars: list[Bar], majors: list[Section], minor_starts: list[int]
) -> list[Section]:
    """Split each major section at the minor boundaries inside it.

    A minor boundary that coincides with a major one adds nothing, and a major section with no
    internal step needs no children.
    """
    nested: list[Section] = []
    for parent in majors:
        inside = [b for b in minor_starts if parent.bar_start < b <= parent.bar_end]
        if not inside:
            continue
        starts = [parent.bar_start, *inside]
        for position, start in enumerate(starts):
            end = starts[position + 1] - 1 if position + 1 < len(starts) else parent.bar_end
            if end < start:
                continue
            nested.append(
                Section(
                    name=f"{parent.name}.{position}",
                    level="minor",
                    bar_start=start,
                    bar_end=end,
                    energy=_mean_energy(bars, start, end),
                )
            )
    return nested


def _positional_name(position: int, total: int) -> str:
    if position == 0:
        return "intro"
    if position == total - 1 and total > 1:
        return "outro"
    return f"s{position}"


def _mean_energy(bars: list[Bar], start: int, end: int) -> float:
    inside = [b.rms for b in bars if start <= b.index <= end]
    return float(np.mean(inside)) if inside else 0.0


def low_band_onset(y: np.ndarray, sr: int) -> float | None:
    """When the drums arrive, measured at frame resolution and independent of any grid.

    This is the anchor the fitted grid gets validated against, so it must not be derived from
    the grid: a bar-quantised answer would agree with every tempo by construction. Returns
    None when the track has no dominant low-band entry to check against.
    """
    spectrum = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=ONSET_HOP))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    times = librosa.times_like(spectrum, sr=sr, hop_length=ONSET_HOP, n_fft=N_FFT)
    low = spectrum[freqs < LOW_HZ].mean(axis=0)

    window = max(1, int(ONSET_WINDOW_S * sr / ONSET_HOP))
    if len(low) < 3 * window:
        return None

    kernel = np.ones(window) / window
    smoothed = np.convolve(low, kernel, mode="valid")
    before, after = smoothed[:-window], smoothed[window:]
    usable = before > 1e-9
    if not usable.any():
        return None

    ratios = np.where(usable, after / np.maximum(before, 1e-9), 0.0)
    peak = int(np.argmax(ratios))
    if ratios[peak] < MAJOR_RATIO:
        return None

    # The rolling ratio locates the transition to within a window; the crossing of a level a
    # quarter of the way up locates the moment itself.
    threshold = before[peak] + ONSET_RISE_FRACTION * (after[peak] - before[peak])
    search_from = peak
    search_to = min(len(low), peak + 2 * window)
    crossings = np.flatnonzero(low[search_from:search_to] > threshold)
    if len(crossings) == 0:
        return float(times[min(peak + window, len(times) - 1)])
    return float(times[search_from + int(crossings[0])])
