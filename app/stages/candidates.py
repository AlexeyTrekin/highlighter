"""Candidates: find the exchanges, gate them, and score them.

Implements `spec/005_scoring.md`. The signals come from `analysis/vNN.json`; this stage never
decodes video.
"""

from dataclasses import dataclass

import numpy as np

from app.manifests import analysis as analysis_schema
from app.manifests.analysis import Analysis
from app.manifests.candidates import (
    OPENING_MIN_BARS,
    Candidate,
    Candidates,
    Features,
    Material,
    Origin,
)
from app.manifests.music import Music
from app.manifests.project import Project, ScoringWeights, Source
from app.video import motion

STAGE = "candidates"

# --- window shape -----------------------------------------------------------------------
# Trailing footage after the touche is the camera settling, not the action.
TAIL_S: float = 0.3
# How far before the onset a clip starts, so the approach is present and not just the hit.
LEAD_BARS: float = 0.5
# A short source holds one exchange ending near its end; this is the fallback window when no
# halt is found in it.
SHORT_FALLBACK_S: float = 4.5
# Exchanges closer than this are the same exchange seen twice.
SEPARATION_S: float = 5.0
PEAKS_PER_LONG_SOURCE: int = 3

# --- halt detection ---------------------------------------------------------------------
# After a touch both fighters stop and reset. The stop must last this long to be a halt
# rather than a pause inside an exchange.
SETTLE_S: float = 0.8
# How far up the clip's own quiet-to-busy range still counts as stopped. Relative because
# absolute activity varies with distance, lens and light.
SETTLE_FRACTION: float = 0.25
# A halt ends an exchange, so there must have been one: activity has to reach this far up the
# range within `ACTION_LOOKBACK_S` before the fall.
ACTION_FRACTION: float = 0.5
ACTION_LOOKBACK_S: float = 1.5
# An onset is where activity climbs past this multiple of the rolling median.
ONSET_MULTIPLE: float = 2.0

# --- gates ------------------------------------------------------------------------------
BOTH_VISIBLE_MIN: float = 0.7
# Two fighters are in measure — close enough to hit each other — below this many body-heights.
IN_MEASURE_GAP: float = 0.7
# A cut moves the brightness this far in one sample *and* far more than the steps around it.
# The second test is what separates a cut from a pan into bright sky, which travels just as far
# but does it evenly — and this is a hard drop, so condemning a pan loses real footage.
SCENE_CUT_BRIGHTNESS: float = 25.0
SCENE_CUT_RATIO: float = 4.0

# --- material ---------------------------------------------------------------------------
# Fencing swings the distance between the fighters: they close to hit and break to reset.
# Motion alone cannot tell it from an embrace or a salute-with-a-clash, both of which are
# vigorous. What separates them is whether that distance *moves* (`spec/005_scoring.md`).
ACTION_VISIBLE_FRAC: float = 0.6
# Gap swing, in body-heights, below which the pair is holding its distance rather than
# fencing. An embrace sits near zero and stays; a salute sits wide and stays.
STABLE_GAP_VARIATION: float = 0.25
# Crossing from out of measure to in, or back, is the shape of an exchange.
ACTION_CROSSINGS: int = 1

# --- non-exchange windows -----------------------------------------------------------------
# The intro wants warm-ups, walk-ons, salutes and hugs. None of them produce a halt, so a
# purely halt-anchored stage can never propose one at all; they are found as stretches where
# the fighters hold their distance.
STABLE_WINDOWS_PER_SOURCE: int = 1
STABLE_MIN_S: float = 2.0


@dataclass(frozen=True)
class Window:
    """A proposed window, and how it came to be proposed.

    The origin matters downstream: an exchange is worthless without both fighters in frame,
    while a walk-on with one person is exactly what the drumless intro wants.
    """

    start: float
    end: float
    anchor: float
    origin: Origin


def resting_level(smoothed: np.ndarray) -> tuple[float, float]:
    """The clip's quiet level and its busy level.

    Both are percentiles rather than the extremes, so one blurred frame or one still moment
    does not define the scale the whole clip is judged against.
    """
    return float(np.percentile(smoothed, 25)), float(np.percentile(smoothed, 95))


def halts(stamps: np.ndarray, activity: np.ndarray) -> list[int]:
    """Indices where activity falls and stays down — the referee's halt.

    In HEMA the stop is far more detectable than the hit: after a touch both fighters break
    off and reset, while the hit itself is a few frames of blur. The halt is what a clip is
    built backwards from.

    "Settled" is measured against the clip's own range rather than its median. A clip is
    mostly *not* fencing — approach, reset, the referee talking — so its median sits at the
    resting level and nothing can fall below it.
    """
    if len(activity) < 3:
        return []

    smoothed = motion.smooth(activity)
    rest, busy = resting_level(smoothed)
    if busy - rest <= 1e-9:
        return []

    settle_level = rest + SETTLE_FRACTION * (busy - rest)
    action_level = rest + ACTION_FRACTION * (busy - rest)

    found: list[int] = []
    for index in range(1, len(smoothed) - 1):
        if smoothed[index] >= smoothed[index - 1]:
            continue

        # The clip must actually contain the settling period. Accepting whatever samples
        # happen to remain lets the last frames of a recording cut off mid-exchange read as a
        # halt — and the smoother's zero-padded edge makes that final sample look quieter
        # than it is, so the two failures compound.
        if stamps[-1] - stamps[index] < SETTLE_S:
            continue
        after = (stamps > stamps[index]) & (stamps <= stamps[index] + SETTLE_S)
        if not after.any() or smoothed[after].max() > settle_level:
            continue

        # A quiet opening — the camera coming up, the fighters walking on — is not a halt.
        # Requiring real activity just before the fall is what separates the referee's halt
        # from a clip that simply started calm.
        before = (stamps >= stamps[index] - ACTION_LOOKBACK_S) & (stamps < stamps[index])
        if not before.any() or smoothed[before].max() < action_level:
            continue

        found.append(index)
    return found


def onset_before(stamps: np.ndarray, activity: np.ndarray, halt: int) -> float:
    """When the action leading to this halt began.

    Walks back from the halt to the last moment activity was still at rest, so the clip opens
    on the approach rather than mid-exchange.
    """
    smoothed = motion.smooth(activity)
    rest, busy = resting_level(smoothed)
    threshold = min(ONSET_MULTIPLE * max(rest, 1e-9), rest + SETTLE_FRACTION * (busy - rest))
    for index in range(halt, 0, -1):
        if smoothed[index] <= threshold:
            return float(stamps[index])
    return float(stamps[0])


def windows(source: Source, data: Analysis, bar_s: float) -> list[Window]:
    """Candidate windows as `(start, end, anchor)` in source seconds.

    A long source yields at most `PEAKS_PER_LONG_SOURCE` of them, so the budget goes to
    windows that could actually be cut. Recordings often open mid-action — the camera comes up
    on an exchange already under way — and that produces a real halt a second in, whose window
    is far too short to fill a slot. Letting one consume the budget costs a genuine exchange
    later in the same clip.

    Windows that could never be cut are still returned, so they reach the manifest with a
    recorded reason rather than disappearing (`spec/002_manifests.md`). Viable halts that lose
    the budget are a different case and are simply not proposed — they were beaten, not
    rejected, and recording every near-miss would bury the reasons that matter.
    """
    stamps = analysis_schema.times(data)
    activity = analysis_schema.activity(data)
    if len(stamps) == 0:
        return []

    calm = stable_windows(source, data, bar_s) + solo_windows(source, data, bar_s)

    built = {
        index: _window_around(stamps, activity, index, source.duration_s, bar_s)
        for index in halts(stamps, activity)
    }
    minimum = OPENING_MIN_BARS * bar_s
    viable = [index for index, window in built.items() if window.end >= minimum]
    unusable = [built[index] for index in built if index not in viable]

    if not viable and source.shape == "short":
        # The touche is near the end by construction, so the tail is the exchange — whether
        # no halt was found at all, or the only one sits too early to be cut from
        # (`spec/005_scoring.md`). Recordings routinely open mid-action, so the second case
        # is as common as the first and losing the clip to it costs a real exchange.
        end = max(0.0, min(source.duration_s - TAIL_S, source.duration_s))
        start = max(0.0, end - SHORT_FALLBACK_S)
        return [Window(start=start, end=end, anchor=end, origin="fallback"), *calm, *unusable]

    # A short source holds one exchange, ending at its last halt. A long one holds several.
    chosen = [viable[-1]] if source.shape == "short" else _rank_halts(stamps, activity, viable)

    picked = [built[index] for index in chosen]
    return picked + _without_overlaps(calm, picked) + unusable


def _without_overlaps(calm: list[Window], chosen: list[Window]) -> list[Window]:
    """Drop calm windows that describe footage an exchange window already covers.

    The gap holds steady during the reset right after a halt, which is exactly where a stable
    stretch is easiest to find — and the two clips would then show the same seconds twice.
    """
    return [
        window
        for window in calm
        if not any(window.start < other.end and other.start < window.end for other in chosen)
    ]


def stable_windows(source: Source, data: Analysis, bar_s: float) -> list[Window]:
    """Stretches where the fighters hold their distance.

    A hug, a salute, a walk-on: none of them produce a halt, so a halt-anchored stage proposes
    none of them and the drumless intro has nothing honest to draw on. Found by looking for
    the opposite of an exchange — a run of frames where the gap simply does not move, however
    energetic the people in it are.
    """
    stamps = analysis_schema.times(data)
    gaps = analysis_schema.gaps(data)
    if len(stamps) < 3:
        return []

    span_s = max(STABLE_MIN_S, OPENING_MIN_BARS * bar_s)
    step = data.sample_step / (data.fps or 30.0)
    minimum = max(3, int(round(span_s / step)) + 1)
    if len(stamps) < minimum:
        return []

    best: tuple[int, float, int] | None = None
    for start_index in range(len(stamps) - minimum + 1):
        length = _stable_run(gaps, start_index, minimum)
        if length is None:
            continue
        variation = gap_variation(gaps[start_index : start_index + length])
        # Longest first: a clip is anchored at its window end and reaches back the length of
        # its slot, so a window shorter than the slot would put unexamined footage on screen.
        # Length is what decides which slots this window may fill at all.
        key = (length, -(variation or 0.0), -start_index)
        if best is None or key > (best[0], -best[1], -best[2]):
            best = (length, variation or 0.0, start_index)

    if best is None:
        return []
    length, _, start_index = best
    start = float(stamps[start_index])
    end = min(float(stamps[start_index + length - 1]), source.duration_s)
    return [Window(start=start, end=end, anchor=end, origin="calm")][:STABLE_WINDOWS_PER_SOURCE]


def _stable_run(gaps: np.ndarray, start_index: int, minimum: int) -> int | None:
    """How far the gap holds steady from `start_index`, or None if it never does."""
    length = None
    for end in range(start_index + minimum, len(gaps) + 1):
        span = gaps[start_index:end]
        finite = span[np.isfinite(span)]
        if len(finite) < 3 or len(finite) < 0.6 * len(span):
            break
        variation = gap_variation(finite)
        if variation is None or variation > STABLE_GAP_VARIATION:
            break
        if measure_crossings(finite) > 0:
            break
        length = end - start_index
    return length


def solo_windows(source: Source, data: Analysis, bar_s: float) -> list[Window]:
    """Stretches where only one fighter is on camera.

    A walk-on is one person crossing the frame, which is intro material and which
    `stable_windows` structurally cannot find: measuring a gap needs two fighters, so a
    one-person stretch has no gap to be stable. Rare — a handful across a whole tournament —
    but the drumless intro only needs a few.
    """
    stamps = analysis_schema.times(data)
    if len(stamps) < 3:
        return []

    span_s = max(STABLE_MIN_S, OPENING_MIN_BARS * bar_s)
    # Exactly one, not "one or fewer". A stretch with no boxes is a camera on the floor, a
    # crowd, or a detector failure — and the intro orders by fewest fighters on camera, so
    # counting empty frames as a walk-on would open the reel on nothing.
    alone = np.array([len(row.boxes) == 1 for row in data.rows], dtype=bool)

    best: tuple[float, int, int] | None = None
    start_index = None
    for index, is_alone in enumerate([*alone, False]):
        if is_alone and start_index is None:
            start_index = index
        elif not is_alone and start_index is not None:
            end_index = index - 1
            length = float(stamps[end_index] - stamps[start_index])
            if length >= span_s and (best is None or length > best[0]):
                best = (length, start_index, end_index)
            start_index = None

    if best is None:
        return []
    _, first, last = best
    end = min(float(stamps[last]), source.duration_s)
    return [Window(start=float(stamps[first]), end=end, anchor=end, origin="calm")]


def _rank_halts(stamps: np.ndarray, activity: np.ndarray, viable: list[int]) -> list[int]:
    """The busiest halts, spread out so two do not describe the same exchange."""
    smoothed = motion.smooth(activity)
    chosen: list[int] = []
    for index in sorted(viable, key=lambda i: -smoothed[max(0, i - 1)]):
        if any(abs(stamps[index] - stamps[taken]) < SEPARATION_S for taken in chosen):
            continue
        chosen.append(index)
        if len(chosen) == PEAKS_PER_LONG_SOURCE:
            break
    return sorted(chosen)


def _window_around(
    stamps: np.ndarray, activity: np.ndarray, halt: int, duration: float, bar_s: float
) -> Window:
    anchor = min(float(stamps[halt]) + TAIL_S, duration)
    onset = onset_before(stamps, activity, halt)
    return Window(
        start=max(0.0, onset - LEAD_BARS * bar_s), end=anchor, anchor=anchor, origin="halt"
    )


def measure(data: Analysis, start: float, end: float) -> Features:
    """The window's features, all read from the analysis."""
    mask = analysis_schema.window_mask(data, start, end)
    if not mask.any():
        return Features()

    activity = motion.smooth(analysis_schema.activity(data))[mask]
    gaps = analysis_schema.gaps(data)[mask]
    finite = gaps[np.isfinite(gaps)]

    return Features(
        peak_activity=float(activity.max()) if len(activity) else 0.0,
        median_sharpness=float(np.median(analysis_schema.sharpness(data)[mask])),
        both_visible_frac=float(analysis_schema.both_visible(data)[mask].mean()),
        min_gap=float(finite.min()) if len(finite) else None,
        closing_speed=closing_speed(data, start, end),
        gap_variation=gap_variation(finite),
        measure_crossings=measure_crossings(finite),
    )


def gap_variation(gaps: np.ndarray) -> float | None:
    """How far the distance between the fighters ranges, in body-heights.

    The interquartile range rather than the full spread, so one frame where a box is
    mis-detected does not make a steady embrace look like an exchange.
    """
    if len(gaps) < 3:
        return None
    return float(np.percentile(gaps, 75) - np.percentile(gaps, 25))


def measure_crossings(gaps: np.ndarray) -> int:
    """How often the pair moves from out of measure to in, or back.

    An exchange does this at least once by definition — you cannot hit from out of measure.
    Two people hugging, or standing at salute, never do.
    """
    if len(gaps) < 2:
        return 0
    inside = gaps < IN_MEASURE_GAP
    return int(np.count_nonzero(inside[1:] != inside[:-1]))


def closing_speed(data: Analysis, start: float, end: float) -> float | None:
    """How fast the fighters converge in the last moments before the halt.

    The discriminator between a committed attack and flailing: large limb motion without
    closing is an exchange of nothing. This is the box-centre baseline `spec/005_scoring.md`
    specifies for when no pose model is present — coarser than a leading hand, and free.
    """
    mask = analysis_schema.window_mask(data, max(start, end - 0.5), end)
    gaps = analysis_schema.gaps(data)[mask]
    stamps = analysis_schema.times(data)[mask]
    finite = np.isfinite(gaps)
    if finite.sum() < 2:
        return None

    gaps, stamps = gaps[finite], stamps[finite]
    elapsed = float(stamps[-1] - stamps[0])
    if elapsed <= 0:
        return None
    return float((gaps[0] - gaps[-1]) / elapsed)


def classify(features: Features) -> Material:
    """Whether the window shows fencing, something else, or neither clearly.

    Keyed on whether the distance between the fighters *moves*, not on how much motion there
    is. Vigour cannot separate the cases: a hug is dynamic and a salute can include a clash.
    Fencing closes and breaks repeatedly; an embrace comes together and stays; a salute or a
    walk-on holds its distance. So the gap swings for one and holds for the others.

    `unknown` is a real answer. A window that neither swings nor clearly holds is undecided,
    and the director treats it as unconstrained rather than trusting a coin toss
    (`spec/005_scoring.md`).
    """
    if features.both_visible_frac < ACTION_VISIBLE_FRAC:
        # One person in frame is a walk-on, not an exchange.
        return "non_action"

    if features.gap_variation is None:
        return "unknown"

    swings = (
        features.measure_crossings >= ACTION_CROSSINGS
        or features.gap_variation > STABLE_GAP_VARIATION
    )
    if swings and features.min_gap is not None and features.min_gap < IN_MEASURE_GAP:
        return "action"
    if features.gap_variation <= STABLE_GAP_VARIATION and features.measure_crossings == 0:
        return "non_action"
    return "unknown"


def score(features: Features, weights: ScoringWeights) -> float:
    """Composite interestingness in [0, 1].

    Weights are configuration rather than constants because they are exactly what the
    benchmark tunes against recorded human verdicts (`spec/005_scoring.md`).
    """
    closing = (features.closing_speed or 0.0) / weights.closing_scale
    parts = {
        "peak_activity": min(1.0, features.peak_activity / weights.activity_scale),
        "closing_speed": float(np.clip(closing, 0.0, 1.0)),
        "both_visible_frac": features.both_visible_frac,
        "min_gap": _gap_score(features.min_gap),
        "median_sharpness": min(1.0, features.median_sharpness / weights.sharpness_scale),
    }
    total = sum(weights.for_feature(name) for name in parts)
    if total <= 0:
        return 0.0
    return float(sum(value * weights.for_feature(name) for name, value in parts.items()) / total)


def _gap_score(min_gap: float | None) -> float:
    """Closer is better, and never having both fighters in frame scores nothing."""
    if min_gap is None:
        return 0.0
    return float(np.clip(1.0 - min_gap / IN_MEASURE_GAP, 0.0, 1.0))


def clamp_to_source(candidate: Candidate, duration: float, bar_s: float) -> None:
    """Hold the window inside its file, and drop it if nothing could be cut from it.

    Clamped here so no later stage has to defend against a window reaching past the end of its
    source (`spec/002_manifests.md`); a window that cannot fill even the shortest slot is not a
    weak candidate but no candidate at all (`spec/005_scoring.md`).
    """
    candidate.end = min(candidate.end, duration)
    candidate.anchor = min(candidate.anchor, candidate.end)
    candidate.start = min(candidate.start, candidate.end)
    if candidate.end < OPENING_MIN_BARS * bar_s:
        candidate.flags.append("source_too_short")


def apply_gates(candidate: Candidate, data: Analysis, bar_s: float, duration: float) -> None:
    """Every hard drop from `spec/005_scoring.md`, with the reason recorded."""
    clamp_to_source(candidate, duration, bar_s)

    # An exchange is worthless without both fighters in frame. A walk-on with one person is
    # not — it is exactly what the drumless intro wants — so the gate follows the origin.
    if candidate.origin != "calm" and candidate.features.both_visible_frac < BOTH_VISIBLE_MIN:
        candidate.flags.append("fighters_not_both_visible")
    if scene_cut_inside(data, candidate.start, candidate.end):
        candidate.flags.append("scene_cut")


def scene_cut_inside(data: Analysis, start: float, end: float) -> bool:
    """Whether the shot changed or the camera was dropped inside the window.

    A cut moves the brightness *and leaves it moved*; a pan into bright sky does the same, so
    a naive threshold on the frame-to-frame delta condemns ordinary footage — that rule was
    already measured wrong once and removed from the render QA. Here the same form would be
    worse: this is a hard drop, not a warning, and the samples are 5 frames apart, so a normal
    pan clears any per-frame threshold easily.

    A cut is a *discontinuity*: one step far larger than the steps around it. A pan is a ramp,
    where every step is much the same size — however far the brightness travels in total.
    """
    mask = analysis_schema.window_mask(data, start, end)
    brightness = np.array([row.brightness for row in data.rows])[mask]
    if len(brightness) < 4:
        return False

    steps = np.abs(np.diff(brightness))
    typical = float(np.median(steps))
    largest = float(steps.max())
    return largest > SCENE_CUT_BRIGHTNESS and largest > SCENE_CUT_RATIO * max(typical, 1e-6)


def run(project: Project, music: Music, analyses: dict[str, Analysis]) -> Candidates:
    """Propose, gate and score windows for every analysed source."""
    bar_s = music.grid.bar_s
    weights = project.options.weights
    found: list[Candidate] = []
    index = 1

    for source in project.sources:
        data = analyses.get(source.id)
        if data is None:
            continue
        for window in windows(source, data, bar_s):
            features = measure(data, window.start, window.end)
            candidate = Candidate(
                id=f"c{index:03d}",
                source_id=source.id,
                start=window.start,
                end=window.end,
                anchor=window.anchor,
                kind=source.shape,
                origin=window.origin,
                material=classify(features),
                features=features,
                score=score(features, weights),
            )
            apply_gates(candidate, data, bar_s, source.duration_s)
            found.append(candidate)
            index += 1

    return Candidates(candidates=found)
