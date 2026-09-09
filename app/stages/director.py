"""Director: place candidates on the music timeline and emit the EDL.

Order the user set is binding and comes first (`spec/007_review_ui.md`). Everything left over is
score-ranked with a source-variety tiebreak, not the section-matched build `spec/006_music.md`
describes; that arrives with WAL step 4.1. The structural rules — fillable slots, cuts on
musical events, material matching, determinism — are implemented for real, because they are
what the prototype got wrong.
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
            clone.anchor = min(max(clone.anchor, trim.start), trim.end)
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
    quiet_bars = music_stage.quiet_opening_bars(music.sections)

    clips: list[Clip] = []
    previous_source: str | None = None
    slots = plan_slots(music, total_bars)
    pinned = pinned_positions(pool, review, len(slots))

    # Front to back, which is also what settles the one contest between two preferences: with a
    # single calm window and both a quiet opening and a coda wanting it, the opening takes it. An
    # action clip under a quiet opening is jarring; under a fade-out it is a wasted finale, and
    # `fade_target` reports that one.
    landed, _ = walk_pins(pinned, slots, project, music)
    placed: set[str] = set()

    for index, (slot, bars) in enumerate(slots):
        chosen = None
        waiting: set[str] = set()
        due = landed.get(index)
        if due is not None and due.id not in placed:
            chosen = (due, pin_reason(review, due))
        if chosen is None:
            # A clip whose turn has not come is held back: letting the score pick it now would
            # place it ahead of a clip the user put before it.
            waiting = {c.id for at, c in landed.items() if at > index and c.id not in placed}
            chosen = choose(
                [c for c in pool if c.id not in waiting],
                project,
                music,
                bars,
                slot,
                quiet_bars,
                previous_source,
                total_bars,
            )
        if chosen is None and waiting:
            # Only a clip being held back can fill this slot. Placing it early keeps it ahead of
            # everything still queued behind it, and the reel is still built — ending here
            # instead would hide footage the user cannot then judge (`spec/006_music.md`).
            chosen = choose(
                pool, project, music, bars, slot, quiet_bars, previous_source, total_bars
            )
            if chosen is not None:
                chosen = (chosen[0], "brought forward: nothing else could fill this slot")
        if chosen is None:
            # Skipping would leave a hole in the timeline and every later clip would start on
            # the wrong bar, so the reel ends here instead.
            break
        candidate, reason = chosen
        placed.add(candidate.id)
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


def pin_reason(review: Review, candidate: Candidate) -> str:
    """Why this clip is here, in the terms the user used to say so.

    Their own numbering, not the slot it landed in: a clip pinned second may be third on screen
    because the second slot was too long for it, and "3 in their order" would describe a request
    nobody made.
    """
    order = review.order
    if order.mode == "strict" and candidate.id in order.sequence:
        reason = f"pinned by the user, {order.sequence.index(candidate.id) + 1} in their sequence"
    else:
        weight = review_schema.effective_weights(order).get(candidate.id)
        reason = (
            "pinned by the user" if weight is None else f"pinned by the user at weight {weight:g}"
        )
    if candidate.flags:
        reason += f"; kept despite {', '.join(candidate.flags)}"
    return reason


def walk_pins(
    pinned: dict[int, Candidate],
    slots: list[tuple[int, int]],
    project: Project,
    music: Music,
) -> tuple[dict[int, Candidate], list[Candidate]]:
    """Which slot each pinned clip lands in, and which pins no slot can hold.

    A pin is binding and outranks every preference the director has: the user can see the clip
    and hear the track (`spec/007_review_ui.md`). What binds is the **order**, not the slot
    number — slots are one, two or three bars, and a clip too short for the one its turn lands
    on takes the next that fits rather than losing its place in the sequence altogether.

    Taken only from the head of the queue, so a clip never overtakes one the user put before it.
    One that no remaining slot can hold gives up its turn rather than blocking everything behind
    it, and comes back in the second return value so the conflict report can say so.

    Depends on nothing but the queue and the slot lengths, so `run` and `unhonoured_keeps` can
    each call it and agree about the outcome by construction rather than by coincidence.
    """
    pending = [candidate for _, candidate in sorted(pinned.items())]
    turn = {candidate.id: position for position, candidate in pinned.items()}

    landed: dict[int, Candidate] = {}
    unplaceable: list[Candidate] = []
    for index, (_, bars) in enumerate(slots):
        while pending and turn[pending[0].id] <= index:
            if fills(pending[0], project, music, bars):
                landed[index] = pending.pop(0)
                break
            if any(fills(pending[0], project, music, later) for _, later in slots[index + 1 :]):
                break
            unplaceable.append(pending.pop(0))
    return landed, [*unplaceable, *pending]


def pinned_positions(
    pool: list[Candidate], review: Review, slot_count: int
) -> dict[int, Candidate]:
    """Where in the reel each pinned clip is due (`spec/007_review_ui.md`).

    Positions are places in the running order, never bars: the slot plan decides how long each
    one is, and a clip whose turn lands on a slot it cannot fill takes the next that fits.
    `pool` is already in the director's total order, so equal weights — a batch the user said
    nothing more precise about — come out in a stable order rather than a dict's.
    """
    order = review.order
    by_id = {c.id: c for c in pool}
    if order.mode == "strict":
        wanted = [by_id[cid] for cid in dict.fromkeys(order.sequence) if cid in by_id]
        return dict(enumerate(wanted[:slot_count]))
    if order.mode != "weighted" or slot_count == 0:
        return {}

    weights = review_schema.effective_weights(order)
    rank = {c.id: index for index, c in enumerate(pool)}
    weighted = sorted(
        (c for c in pool if c.id in weights),
        key=lambda c: (weights[c.id], rank[c.id]),
    )[:slot_count]
    if not weighted:
        return {}

    values = [weights[c.id] for c in weighted]
    if max(values) == min(values):
        # One batch and nothing to bracket, so the weight is read as a place on the axis: the
        # batch sits together, that far through the reel.
        share = values[0] / review_schema.WEIGHT_MAX
        start = round(share * (slot_count - len(weighted)))
        return {start + offset: candidate for offset, candidate in enumerate(weighted)}

    free = _share_free_slots(values, slot_count - len(weighted))
    placed: dict[int, Candidate] = {}
    cursor = 0
    for index, candidate in enumerate(weighted):
        placed[cursor] = candidate
        cursor += 1 + (free[index] if index < len(free) else 0)
    return placed


def _share_free_slots(weights: list[float], free: int) -> list[int]:
    """Free positions between each consecutive pair of weighted clips.

    Shared in proportion to the gap between their weights, so 10 → 50 takes about twice the room
    of 50 → 70 (`spec/007_review_ui.md`). Largest remainder, so the parts add up to the whole
    and the result does not depend on iteration order.
    """
    gaps = [later - earlier for earlier, later in zip(weights, weights[1:], strict=False)]
    total = sum(gaps)
    if free <= 0 or total <= 0:
        return [0] * len(gaps)

    exact = [gap / total * free for gap in gaps]
    shares = [int(value) for value in exact]
    remainder = free - sum(shares)
    for index in sorted(range(len(gaps)), key=lambda i: (-(exact[i] - shares[i]), i))[:remainder]:
        shares[index] += 1
    return shares


def unhonoured_keeps(
    project: Project, music: Music, candidates: Candidates, review: Review, edl: Edl
) -> list[tuple[str, str]]:
    """Clips the user asked for — by keeping or by pinning — that did not reach the reel.

    A keep is the strongest signal the pipeline gets and a pin is stronger still, and either can
    be impossible: too short for any slot this reel has, dropped in the same breath, or beaten
    to the last slot. Letting one vanish silently is the worst outcome available: the user made
    a decision, the reel ignored it, and nothing said so (`spec/007_review_ui.md`).

    The reason is worked out against the slot plan the reel was actually built from, so it names
    the rule that excluded this clip rather than a plausible one.
    """
    placed = {clip.candidate_id for clip in edl.clips}
    adjusted = {c.id: c for c in applied(candidates, review).candidates}
    slots = plan_slots(music, bar_budget(music, project.options.duration_s))

    asked_for = [cid for cid in review.verdicts if review_schema.is_kept(review, cid)]
    asked_for += [cid for cid in review_schema.pins(review.order) if cid not in asked_for]

    pool = ranked(project, music, Candidates(candidates=list(adjusted.values())), review)
    cuttable = {c.id for c in pool}
    pinned = pinned_positions(pool, review, len(slots))
    _, unplaceable = walk_pins(pinned, slots, project, music)
    stranded = {c.id for c in unplaceable}
    positioned = {c.id for c in pinned.values()}
    pins = set(review_schema.pins(review.order))

    conflicts: list[tuple[str, str]] = []
    for candidate_id in asked_for:
        if candidate_id in placed:
            continue
        candidate = adjusted.get(candidate_id)
        if candidate is None:
            conflicts.append((candidate_id, "no such candidate"))
        elif review_schema.is_dropped(review, candidate_id):
            conflicts.append((candidate_id, "asked for and dropped in the same review"))
        elif candidate_id in stranded:
            # Its turn came and no slot from there on could hold it. "Beaten to the last slot"
            # would send the user hunting a competitor that never existed.
            conflicts.append(
                (
                    candidate_id,
                    "no slot from its place in your order onwards is short enough for it",
                )
            )
        elif candidate_id in pins and candidate_id in cuttable and candidate_id not in positioned:
            held = len(edl.clips)
            conflicts.append(
                (
                    candidate_id,
                    f"pinned past the end of the reel; it holds {held} clip"
                    f"{'' if held == 1 else 's'}",
                )
            )
        else:
            conflicts.append((candidate_id, _why_unplaced(candidate, project, music, slots)))
    return sorted(conflicts)


def _why_unplaced(
    candidate: Candidate,
    project: Project,
    music: Music,
    slots: list[tuple[int, int]],
) -> str:
    """Which rule kept this clip out, in terms of the reel that was actually built."""
    if not fills(candidate, project, music, OPENING_MIN_BARS):
        source = source_by_id(project, candidate.source_id)
        length = min(candidate.end, source.duration_s) - candidate.start
        after = " after trimming" if candidate.trimmed else ""
        return (
            f"only {length:.2f}s{after}; the shortest slot is "
            f"{OPENING_MIN_BARS * music.grid.bar_s:.2f}s"
        )
    if any(fills(candidate, project, music, bars) for _, bars in slots):
        return "beaten to the last slot"
    shortest = min(bars for _, bars in slots)
    return (
        f"fills none of this reel's slots; the shortest is {shortest} "
        f"bar{'' if shortest == 1 else 's'} ({shortest * music.grid.bar_s:.2f}s)"
    )


def ranked(
    project: Project, music: Music, candidates: Candidates, review: Review
) -> list[Candidate]:
    """Usable candidates, best first, under a total order.

    A clip the user marked **keep** sorts ahead of everything the scorer liked. They watched
    the footage; the score is a proxy for that and loses to it. The id is the final tiebreak so
    equal scores never fall back on set or dict iteration order, which would let clips move
    between runs for no reason the user can see.

    A keep also overrides the quality gates, which is what rescuing a dropped candidate means
    (`spec/007_review_ui.md`): the gates are a guess about what a viewer would reject, and a
    viewer who has looked at the clip outranks them. Pinning a clip to a position says the same
    thing more strongly, so it lifts the gates too. The bar grid is not overridable — a window
    too short for any slot still cannot be cut — and `unhonoured_keeps` reports that case.
    """
    asked_for = set(review_schema.pins(review.order))
    keep = [
        c
        for c in candidates.candidates
        # A drop is as explicit as a pin, so a clip that is both is not quietly resolved in
        # either direction: it stays out, and `unhonoured_keeps` reports the contradiction.
        if not review_schema.is_dropped(review, c.id)
        and (usable(c) or review_schema.is_kept(review, c.id) or c.id in asked_for)
        and fills(c, project, music, OPENING_MIN_BARS)
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

    Measured from where the clip will actually end — `to_clip` pulls the out point back to
    end-of-file — because a window whose end is past EOF reaches back from the shorter point
    and would otherwise land before its own start.
    """
    source = source_by_id(project, candidate.source_id)
    if max_bars(candidate, music.grid.bar_s, source.duration_s) < bars:
        return False
    if candidate.origin == "calm" or candidate.trimmed:
        available = min(candidate.end, source.duration_s) - candidate.start
        return available >= bars * music.grid.bar_s - 1e-9
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
    quiet_bars: int,
    previous_source: str | None,
    total_bars: int,
) -> tuple[Candidate, str] | None:
    """Best candidate for this slot, with the reason it was placed there.

    One constraint binds — the source must fill the slot. Everything else here is a preference
    that yields when the footage cannot satisfy it (`spec/006_music.md`): a collection may hold
    no non-fight material at all, and truncating the reel to protect a quiet opening would trade
    a whole section of footage for a preference the viewer can see for themselves.
    """
    quiet = slot < quiet_bars
    eligible = [c for c in pool if fills(c, project, music, bars)]
    if not eligible:
        return None

    # One clip, not the whole outro. `spec/006_music.md` asks for a single coda under the
    # fade, and `fade_target` inspects only the last clip; filtering every slot of a long
    # outro to non-fight material would empty the end of the reel to satisfy a rule about
    # one of them.
    coda = slot + bars >= total_bars and coda_bar(music, total_bars) is not None
    if quiet or coda:
        # Ranked preferences, strongest first, each falling through when it empties the
        # shortlist: material known to be non-fight, then anything not known to be a fight,
        # then whatever is left. `unknown` beating `non_action` on score is how a lunge ends up
        # under a quiet chord — the score ranks how *interesting* a window is, which is the
        # wrong question here — but an unclassified window still beats an exchange.
        eligible = (
            [c for c in eligible if c.material == "non_action"]
            or [c for c in eligible if c.material != "action"]
            or eligible
        )

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
        reason = (
            f"bars {slot}-{slot + bars - 1} open the track quietly; picked {pick.material} material"
        )
    elif coda:
        reason = f"the outro fade covers this clip; picked {pick.material} material"
    else:
        reason = f"highest remaining score ({pick.score:.3f}) that fills {bars} bars"
    if not varied:
        reason += "; no other source could fill this slot"
    if pick.flags:
        reason += f"; kept by the user despite {', '.join(pick.flags)}"
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
