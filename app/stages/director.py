"""Director: place candidates on the music timeline and emit the EDL.

**Placeholder ordering.** Clip choice here is score-ranked with a source-variety tiebreak, not
the section-matched build `spec/006_music.md` describes; that arrives with WAL step 4.1. The
structural rules — fillable slots, cuts on musical events, material matching, determinism —
are implemented for real, because they are what the prototype got wrong.
"""

from app.manifests import music as music_schema
from app.manifests import review as review_schema
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
from app.manifests.review import Review
from app.stages import music as music_stage

STAGE = "director"

# Two bars is one action; three is an action with its approach. Four is for something worth
# lingering on, which the placeholder has no grounds to claim of anything.
CLIP_BARS: int = 2
CLIP_BARS_LONG: int = 3


class NoUsableCandidates(RuntimeError):
    """Nothing survived the quality gates, so there is no reel to build."""


def applied(candidates: Candidates, review: Review) -> Candidates:
    """Candidates with the human's decisions folded in.

    A dropped candidate keeps its place in the manifest and gains a flag, so the decision stays
    auditable and reversible (`spec/002_manifests.md`). A trim replaces the window outright:
    the user looked at the footage, which no measurement here did.
    """
    adjusted: list[Candidate] = []
    for candidate in candidates.candidates:
        clone = candidate.model_copy(deep=True)
        if review_schema.is_dropped(review, clone.id):
            clone.flags = [*clone.flags, "dropped_by_user"]
        trim = review_schema.trim_for(review, clone.id)
        if trim is not None:
            clone.start, clone.end = trim.start, trim.end
            clone.anchor = min(clone.anchor, trim.end)
            clone.trimmed = True
        adjusted.append(clone)
    return Candidates(candidates=adjusted)


def run(
    project: Project, music: Music, candidates: Candidates, review: Review | None = None
) -> Edl:
    """Build the EDL.

    Deterministic by construction: candidates carry a total order and every later choice
    follows from it, so two runs on unchanged inputs produce an identical file
    (`spec/002_manifests.md`).
    """
    grid = music.grid
    review = review or Review()
    pool = ranked(project, music, applied(candidates, review), review)
    if not pool:
        raise NoUsableCandidates("every candidate was dropped by the quality gates")

    total_bars = bar_budget(music, project.options.duration_s)
    drumless = music_stage.drumless_bars(music)

    clips: list[Clip] = []
    previous_source: str | None = None

    for slot, bars in plan_slots(music, total_bars):
        chosen = choose(pool, project, music, bars, slot, drumless, previous_source, total_bars)
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


def unhonoured_keeps(
    project: Project, music: Music, candidates: Candidates, review: Review, edl: Edl
) -> list[tuple[str, str]]:
    """Clips the user marked keep that did not reach the reel, and why.

    A keep is the strongest signal the pipeline gets, and one can still be impossible — trimmed
    below the shortest slot, dropped by a gate, or simply beaten to the last slot. Letting it
    vanish silently is the worst outcome: the user made a decision, the reel ignored it, and
    nothing said so (`spec/007_review_ui.md`).
    """
    placed = {clip.candidate_id for clip in edl.clips}
    adjusted = {c.id: c for c in applied(candidates, review).candidates}

    conflicts: list[tuple[str, str]] = []
    for candidate_id in review.verdicts:
        if not review_schema.is_kept(review, candidate_id) or candidate_id in placed:
            continue
        candidate = adjusted.get(candidate_id)
        if candidate is None:
            conflicts.append((candidate_id, "no such candidate"))
        elif candidate.flags:
            conflicts.append((candidate_id, f"dropped: {', '.join(candidate.flags)}"))
        elif not fills(candidate, project, music, OPENING_MIN_BARS):
            length = candidate.end - candidate.start
            conflicts.append(
                (
                    candidate_id,
                    f"only {length:.2f}s after trimming; the shortest slot is "
                    f"{OPENING_MIN_BARS * music.grid.bar_s:.2f}s",
                )
            )
        else:
            conflicts.append((candidate_id, "the reel ran out of slots"))
    return sorted(conflicts)


def ranked(
    project: Project, music: Music, candidates: Candidates, review: Review
) -> list[Candidate]:
    """Usable candidates, best first, under a total order.

    A clip the user marked **keep** sorts ahead of everything the scorer liked. They watched
    the footage; the score is a proxy for that and loses to it. The id is the final tiebreak so
    equal scores never fall back on set or dict iteration order, which would let clips move
    between runs for no reason the user can see.
    """
    keep = [
        c for c in candidates.candidates if usable(c) and fills(c, project, music, OPENING_MIN_BARS)
    ]
    return sorted(keep, key=lambda c: (not review_schema.is_kept(review, c.id), -c.score, c.id))


def fills(candidate: Candidate, project: Project, music: Music, bars: int) -> bool:
    """Whether this candidate can be cut to `bars` without leaving what was examined.

    A clip is anchored at its window end and reaches back `bars * bar_s`. For an exchange that
    is deliberate — the reach-back is the approach, and the window was only ever the action
    (`spec/005_scoring.md`). For a calm window it is not: the label says what the *window*
    contains, and reaching past its start renders footage no classifier looked at. A two-second
    stable stretch dropped into a two-bar slot brings four seconds to the screen, and the two
    that were never examined are most often the tail of the exchange that preceded it.

    A window a human trimmed binds for the same reason and more strongly: they said which
    seconds they wanted, and reaching outside them shows footage they took out.
    """
    source = source_by_id(project, candidate.source_id)
    if max_bars(candidate, music.grid.bar_s, source.duration_s) < bars:
        return False
    if candidate.origin == "calm" or candidate.trimmed:
        return candidate.end - candidate.start >= bars * music.grid.bar_s - 1e-9
    return True


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
    total_bars: int,
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

    # One clip, not the whole outro. `spec/006_music.md` asks for a single coda under the
    # fade, and `fade_target` inspects only the last clip; filtering every slot of a long
    # outro to non-fight material would empty the end of the reel to satisfy a rule about
    # one of them.
    coda = slot + bars >= total_bars and coda_bar(music, total_bars) is not None
    if quiet or coda:
        # Under a quiet opening or a fade-out, prefer material known to be non-fight over
        # material nothing could classify. `unknown` beating `non_action` on an action score
        # is how a lunge ends up under a quiet chord: the score ranks how *interesting* a
        # window is, which is the wrong question here.
        eligible = [c for c in eligible if c.material == "non_action"] or eligible
        if coda:
            # Preferred rather than required, unlike the drumless intro. An action clip under
            # a quiet opening is jarring; under a fade-out it is merely a wasted finale, and
            # ending the reel early to avoid it would be the worse trade.
            eligible = [c for c in eligible if c.material != "action"] or eligible

    varied = [c for c in eligible if c.source_id != previous_source]
    shortlist = varied or eligible
    if quiet or coda:
        # Order by how *unlike* an exchange the window is, not by how interesting it is. The
        # score ranks fencing quality, and using it here picks the most watchable of the calm
        # clips — which on real footage means fencing at long measure, because holding a
        # distance is exactly what makes a window read as calm. Fewest fighters on camera is
        # the strongest evidence that nothing is being fought.
        shortlist = sorted(shortlist, key=lambda c: (c.features.both_visible_frac, -c.score))
    pick = shortlist[0]

    if quiet:
        reason = f"bars {slot}-{slot + bars - 1} are drumless; picked {pick.material} material"
    elif coda:
        reason = f"the outro fade covers this clip; picked {pick.material} material"
    else:
        reason = f"highest remaining score ({pick.score:.3f}) that fills {bars} bars"
    if not varied:
        reason += "; no other source could fill this slot"
    return pick, reason


def coda_bar(music: Music, total_bars: int) -> int | None:
    """Where the outro begins, if the track has one.

    The last major section is what the fade covers, and `spec/006_music.md` wants a coda
    there rather than the finale.
    """
    majors = [s for s in music.sections if s.level == "major" and s.bar_start < total_bars]
    if len(majors) < 2:
        return None
    return max(s.bar_start for s in majors)


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
