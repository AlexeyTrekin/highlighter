"""Director: place candidates on the music timeline and emit the EDL.

**Placeholder ordering.** Clip choice here is score-ranked with a source-variety tiebreak, not
the section-matched build `spec/006_music.md` describes; that arrives with WAL step 4.1. The
structural rules — fillable slots, cuts on musical events, material matching, determinism —
are implemented for real, because they are what the prototype got wrong.
"""

from app.manifests import music as music_schema
from app.manifests.candidates import (
    MIN_BARS,
    OPENING_MIN_BARS,
    Candidate,
    Candidates,
    max_bars,
    usable,
)
from app.manifests.edl import Clip, Crop, Edl, Output
from app.manifests.music import Music
from app.manifests.project import Project, source_by_id
from app.stages import music as music_stage

STAGE = "director"

# Two bars is one action; three is an action with its approach. Four is for something worth
# lingering on, which the placeholder has no grounds to claim of anything.
CLIP_BARS: int = 2
CLIP_BARS_LONG: int = 3


class NoUsableCandidates(RuntimeError):
    """Nothing survived the quality gates, so there is no reel to build."""


def run(project: Project, music: Music, candidates: Candidates) -> Edl:
    """Build the EDL.

    Deterministic by construction: candidates carry a total order and every later choice
    follows from it, so two runs on unchanged inputs produce an identical file
    (`spec/002_manifests.md`).
    """
    grid = music.grid
    pool = ranked(project, music, candidates)
    if not pool:
        raise NoUsableCandidates("every candidate was dropped by the quality gates")

    total_bars = bar_budget(music, project.options.duration_s)
    drumless = music_stage.drumless_bars(music)

    clips: list[Clip] = []
    previous_source: str | None = None

    for slot, bars in plan_slots(music, total_bars):
        chosen = choose(pool, project, music, bars, slot, drumless, previous_source)
        if chosen is None:
            # Skipping would leave a hole in the timeline and every later clip would start on
            # the wrong bar, so the reel ends here instead.
            break
        candidate, reason = chosen
        pool.remove(candidate)
        previous_source = candidate.source_id
        source = source_by_id(project, candidate.source_id)
        clips.append(to_clip(candidate, music, bars, slot, reason, source.duration_s))

    if not clips:
        raise NoUsableCandidates(
            "no candidate could fill the first slot; every window is shorter than the bar grid"
        )

    return Edl(
        grid=grid,
        music_sections=music.sections,
        output=Output(
            width=project.options.width,
            height=project.options.height,
            fps=project.options.fps,
            duration_s=sum(c.bars for c in clips) * grid.bar_s,
        ),
        clips=clips,
    )


def ranked(project: Project, music: Music, candidates: Candidates) -> list[Candidate]:
    """Usable candidates, best first, under a total order.

    The id is the final tiebreak so equal scores never fall back on set or dict iteration
    order, which would let clips move between runs for no reason the user can see.
    """
    keep = [
        c for c in candidates.candidates if usable(c) and fills(c, project, music, OPENING_MIN_BARS)
    ]
    return sorted(keep, key=lambda c: (-c.score, c.id))


def fills(candidate: Candidate, project: Project, music: Music, bars: int) -> bool:
    """Whether the candidate's source can supply `bars` of footage ending at its window end."""
    source = source_by_id(project, candidate.source_id)
    return max_bars(candidate, music.grid.bar_s, source.duration_s) >= bars


def bar_budget(music: Music, target_s: float) -> int:
    """Whole bars the reel should occupy, capped by the track itself."""
    wanted = max(1, int(round(target_s / music.grid.bar_s)))
    available = len(music.bars) or wanted
    return min(wanted, available)


def spans(music: Music, total_bars: int, level: str) -> list[tuple[int, int]]:
    """Bar ranges delimited by boundaries of `level`, as `(start, length)`."""
    inside = {
        s.bar_start for s in music.sections if s.level == level and 0 < s.bar_start < total_bars
    }
    starts = sorted({0} | inside)
    bounds = [*starts, total_bars]
    return [(a, b - a) for a, b in zip(bounds, bounds[1:], strict=False) if b > a]


def partition(length: int, minimum: int = MIN_BARS) -> list[int]:
    """Split a span into clip lengths.

    Two bars is one action and three is an action with its approach, so a span is filled with
    twos and at most one three. A span shorter than `minimum` holds nothing — returning an
    empty plan is what keeps an unfillable slot out of the timeline.
    """
    if length < minimum:
        return []
    if length < MIN_BARS:
        return [length]
    if length % CLIP_BARS == 0:
        return [CLIP_BARS] * (length // CLIP_BARS)
    return [CLIP_BARS_LONG, *[CLIP_BARS] * ((length - CLIP_BARS_LONG) // CLIP_BARS)]


def plan_slots(music: Music, total_bars: int) -> list[tuple[int, int]]:
    """Every slot in the reel as `(start_bar, bars)`.

    Major boundaries are mandatory, so planning happens inside them. Minor boundaries are
    preferred over plain bar lines and are taken whenever every resulting piece can still hold
    a clip — subdividing into a piece nothing can fill would trade an arbitrary cut for a gap
    (`spec/006_music.md`).
    """
    minor_starts = {s.bar_start for s in music.sections if s.level == "minor"}

    slots: list[tuple[int, int]] = []
    for start, length in spans(music, total_bars, "major"):
        for piece_start, piece_length in _subdivide(start, length, minor_starts):
            cursor = piece_start
            minimum = OPENING_MIN_BARS if piece_start == 0 else MIN_BARS
            for bars in partition(piece_length, minimum):
                slots.append((cursor, bars))
                cursor += bars
                minimum = MIN_BARS
    return slots


def _subdivide(start: int, length: int, minor_starts: set[int]) -> list[tuple[int, int]]:
    """Split a major span at its minor boundaries, or leave it whole.

    The reel's opening piece may be a single bar. Without that exception a section whose first
    musical step falls one bar in can never be cut there, and the cut falls back to a plain bar
    that carries no event — which is the thing `spec/006_music.md` ranks last.
    """
    inside = sorted(b for b in minor_starts if start < b < start + length)
    if not inside:
        return [(start, length)]

    bounds = [start, *inside, start + length]
    pieces = [(a, b - a) for a, b in zip(bounds, bounds[1:], strict=False)]
    if all(size >= _floor_for(piece_start) for piece_start, size in pieces):
        return pieces
    return [(start, length)]


def _floor_for(piece_start: int) -> int:
    return OPENING_MIN_BARS if piece_start == 0 else MIN_BARS


def choose(
    pool: list[Candidate],
    project: Project,
    music: Music,
    bars: int,
    slot: int,
    drumless_bars: int,
    previous_source: str | None,
) -> tuple[Candidate, str] | None:
    """Best candidate for this slot, with the reason it was placed there.

    Two structural constraints bind: the source must fill the slot, and fight material may not
    appear before the drums arrive.
    """
    quiet = slot < drumless_bars
    eligible = [
        c for c in pool if fills(c, project, music, bars) and not (quiet and c.material == "action")
    ]
    if not eligible:
        return None

    varied = [c for c in eligible if c.source_id != previous_source]
    pick = (varied or eligible)[0]

    if quiet:
        reason = f"bars {slot}-{slot + bars - 1} are drumless; picked {pick.material} material"
    else:
        reason = f"highest remaining score ({pick.score:.3f}) that fills {bars} bars"
    if not varied:
        reason += "; no other source could fill this slot"
    return pick, reason


def to_clip(
    candidate: Candidate,
    music: Music,
    bars: int,
    slot: int,
    reason: str,
    source_duration: float,
) -> Clip:
    section = music_schema.section_at_bar(music, slot)
    # Anchored at the window end but never past the file: `max_bars` caps how far a clip
    # reaches back, which is worthless if the point it reaches back *from* is beyond EOF.
    out = min(candidate.end, source_duration)
    return Clip(
        candidate_id=candidate.id,
        source_id=candidate.source_id,
        **{"in": out - bars * music.grid.bar_s},
        out=out,
        bars=bars,
        grid_slot=slot,
        section=section.name if section else "unknown",
        crop=Crop(mode="none"),
        material=candidate.material,
        score=candidate.score,
        order_reason=reason,
        why=f"{candidate.kind} window, peak activity {candidate.features.peak_activity:.1f}",
    )
