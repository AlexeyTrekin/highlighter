"""Candidates: propose windows and apply the quality gates.

**Placeholder scoring.** This stage does not yet implement `spec/005_scoring.md`: there is no
person detection, no camera-compensated activity, no halt detection and no closing speed. It
proposes windows by position and ranks them by a raw frame-difference energy that rewards
flailing over a clean thrust. WAL step 2.1 replaces the scoring; the window contract and the
gates below are already the real ones.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from app.manifests.candidates import MIN_BARS, Candidate, Candidates, Features
from app.manifests.music import Music
from app.manifests.project import Project, Source

STAGE = "candidates"

# A short source holds one exchange ending near its end, so the window is its tail.
SHORT_WINDOW_S: float = 4.5
# Trailing footage after the touche is the camera settling, not the action.
TAIL_TRIM_S: float = 0.3
# Peaks closer than this describe the same exchange.
PEAK_SEPARATION_S: float = 5.0
PEAKS_PER_LONG_SOURCE: int = 3
LONG_LEAD_S: float = 2.4
LONG_TRAIL_S: float = 1.8

SAMPLE_STEP: int = 5
ANALYSIS_WIDTH: int = 320
ANALYSIS_HEIGHT: int = 180
SMOOTH_WIDTH: int = 3

# Activity is a mean absolute difference of 8-bit grey frames, so it shares their scale.
# `score` is contracted as 0–1 (`spec/002_manifests.md`), and downstream readers — the
# benchmark and the review UI — will take that literally.
GREY_LEVELS: float = 255.0


@dataclass(frozen=True)
class Activity:
    """A source's sampled motion signal. Decoding is expensive, so it is computed once."""

    times: np.ndarray
    energy: np.ndarray

    def peak_between(self, start: float, end: float) -> float:
        if len(self.times) == 0:
            return 0.0
        window = (self.times >= start) & (self.times <= end)
        return float(self.energy[window].max()) if window.any() else 0.0


def measure(source: Source) -> Activity:
    """Sample the source and difference successive frames.

    Whole-frame differencing measures the camera as much as the fighters. Subtracting global
    motion needs person boxes, which arrive with the detector, so this is a placeholder that
    ranks badly rather than one that pretends otherwise.
    """
    capture = cv2.VideoCapture(source.path)
    times: list[float] = []
    energies: list[float] = []
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or source.fps
        previous = None
        index = 0
        while True:
            if not capture.grab():
                break
            if index % SAMPLE_STEP == 0:
                ok, frame = capture.retrieve()
                if not ok:
                    break
                small = cv2.cvtColor(
                    cv2.resize(frame, (ANALYSIS_WIDTH, ANALYSIS_HEIGHT)), cv2.COLOR_BGR2GRAY
                ).astype(np.int16)
                if previous is not None:
                    times.append(index / fps)
                    energies.append(float(np.abs(small - previous).mean()))
                previous = small
            index += 1
    finally:
        capture.release()

    return Activity(np.array(times), _smooth(np.array(energies)))


def _smooth(values: np.ndarray) -> np.ndarray:
    if len(values) < SMOOTH_WIDTH:
        return values
    return np.convolve(values, np.ones(SMOOTH_WIDTH) / SMOOTH_WIDTH, mode="same")


def propose(source: Source, activity: Activity) -> list[tuple[float, float, float]]:
    """Windows for one source as `(start, end, anchor)` in source seconds."""
    if source.shape == "short":
        end = max(min(source.duration_s - TAIL_TRIM_S, source.duration_s), 0.0)
        return [(max(0.0, end - SHORT_WINDOW_S), end, end)]

    if len(activity.times) == 0:
        return []

    chosen: list[float] = []
    for index in np.argsort(-activity.energy):
        moment = float(activity.times[index])
        if moment < LONG_LEAD_S or moment > source.duration_s - LONG_TRAIL_S:
            continue
        if any(abs(moment - taken) < PEAK_SEPARATION_S for taken in chosen):
            continue
        chosen.append(moment)
        if len(chosen) == PEAKS_PER_LONG_SOURCE:
            break

    windows = []
    for peak in sorted(chosen):
        end = min(source.duration_s, peak + LONG_TRAIL_S)
        windows.append((max(0.0, peak - LONG_LEAD_S), end, end))
    return windows


def run(project: Project, music: Music) -> Candidates:
    """Propose windows for every source and gate them against the bar grid."""
    bar_s = music.grid.bar_s
    found: list[Candidate] = []
    index = 1

    for source in project.sources:
        activity = measure(source)
        for start, end, anchor in propose(source, activity):
            candidate = Candidate(
                id=f"c{index:03d}",
                source_id=source.id,
                start=start,
                end=end,
                anchor=anchor,
                kind=source.shape,
                features=Features(peak_activity=activity.peak_between(start, end)),
            )
            candidate.score = min(1.0, candidate.features.peak_activity / GREY_LEVELS)
            apply_gates(candidate, bar_s, source.duration_s)
            found.append(candidate)
            index += 1

    return Candidates(candidates=found)


def apply_gates(candidate: Candidate, bar_s: float, source_duration: float) -> None:
    """Clamp the window to the file, then drop it if it cannot be rendered, recording why.

    The window is clamped first so no later stage has to remember to: a window may claim an
    end past the file (a hand-written manifest, or ffprobe's container duration disagreeing
    with the last decodable frame), and an unclamped end anchors the clip past EOF however
    carefully its *length* was capped.

    The minimum-slot gate is then the freeze fix (`spec/005_scoring.md`): a source that cannot
    supply `MIN_BARS` of footage ending at the anchor is not a weak candidate, it is not a
    candidate. Stretching one past the end of its file is what produced frozen tails.
    """
    candidate.end = min(candidate.end, source_duration)
    candidate.anchor = min(candidate.anchor, candidate.end)
    if candidate.end < MIN_BARS * bar_s:
        candidate.flags.append("source_too_short")
