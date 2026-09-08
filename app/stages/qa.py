"""Automated checks that run before a reel is presented (`spec/008_render.md`).

A `fail` blocks calling the reel finished; warnings are reported, never suppressed.
"""

from app.manifests import qa as qa_schema
from app.manifests.edl import Edl
from app.manifests.music import Music, Section
from app.manifests.qa import Check, Qa
from app.stages import music as music_stage
from app.stages.render import ClipRender

BRIGHTNESS_JUMP: float = 12.0

# Counted as identical *pairs*, so this value means three identical frames in a row.
# Converting 24 fps to 30 holds a source frame across two output frames and never three, so
# three is the shortest run that frame-rate conversion cannot explain.
FROZEN_TAIL_FRAMES: int = 2


def run(edl: Edl, music: Music, renders: list[ClipRender], requested_s: float) -> Qa:
    checks: list[Check] = [
        *brightness_jump(renders),
        *frozen_tail(renders),
        *frame_budget(edl, renders),
        *grid_alignment(edl, renders),
        *section_straddle(edl, music),
        material_match(edl, music),
        fade_target(edl),
        consecutive_setup(edl),
        duration(edl, requested_s),
        *not_yet_implemented(),
    ]
    return qa_schema.build(checks)


def not_yet_implemented() -> list[Check]:
    """Record the checks `spec/008_render.md` defines that this build does not run.

    Absent from the report, a reader of `qa.json` cannot tell "did not run" from "passed",
    and an unrun check reads as a clean bill of health.
    """
    return [
        Check(
            name=name,
            target="reel",
            status="warn",
            detail=f"not implemented yet; arrives with {step}",
        )
        for name, step in (("duplicate_footage", "WAL 3.1"), ("target_present", "WAL 5.1"))
    ]


def spike_frames(levels: list[float], threshold: float = BRIGHTNESS_JUMP) -> list[int]:
    """Frames whose brightness departs from both neighbours in the same direction.

    That pattern — out and straight back — is the crop-flash signature. Flagging any large
    frame-to-frame change instead condemns ordinary footage: a camera panning into the sky
    moves 18 levels in a frame and stays there, which a viewer sees as a pan, not a flash.
    """
    found = []
    for index in range(1, len(levels) - 1):
        before = levels[index] - levels[index - 1]
        after = levels[index] - levels[index + 1]
        if before * after > 0 and min(abs(before), abs(after)) > threshold:
            found.append(index)
    return found


def brightness_jump(renders: list[ClipRender]) -> list[Check]:
    """Catch the crop-flash signature: a frame that jumps in brightness and back."""
    offenders = []
    for render in renders:
        spikes = spike_frames(render.brightness)
        if spikes:
            offenders.append(f"{render.clip.candidate_id} (frames {spikes[:5]})")
    if not offenders:
        return [
            Check(
                name="brightness_jump",
                target="reel",
                status="pass",
                detail="no frame departs from both neighbours",
            )
        ]
    return [
        Check(
            name="brightness_jump",
            target=", ".join(offenders),
            status="fail",
            detail=f"frame brightness spikes by more than {BRIGHTNESS_JUMP} and returns",
        )
    ]


def frozen_tail(renders: list[ClipRender]) -> list[Check]:
    """Catch a clip whose picture stops dead because its source ran out."""
    offenders = [
        f"{r.clip.candidate_id} ({r.tail_identical} frames)"
        for r in renders
        if r.tail_identical >= FROZEN_TAIL_FRAMES
    ]
    if not offenders:
        return [Check(name="frozen_tail", target="reel", status="pass", detail="no frozen tails")]
    return [
        Check(
            name="frozen_tail",
            target=", ".join(offenders),
            status="fail",
            detail="clip ends on repeated identical frames; its slot outran the source",
        )
    ]


def frame_budget(edl: Edl, renders: list[ClipRender]) -> list[Check]:
    """Each clip must contain exactly the frames its slot asked for.

    Recomputing the timeline from the EDL can only ever agree with itself. This is the check
    that looks at what came out: a clip short by even a few frames concatenates happily and
    drags every later cut off the beat, and no other check would notice.
    """
    short = [
        f"{r.clip.candidate_id} ({r.observed_frames}/{r.frames})"
        for r in renders
        if r.observed_frames != r.frames
    ]
    if not short:
        return [
            Check(
                name="frame_budget",
                target="reel",
                status="pass",
                detail=f"{sum(r.frames for r in renders)} frames, every clip complete",
            )
        ]
    return [
        Check(
            name="frame_budget",
            target=", ".join(short),
            status="fail",
            detail="clip does not hold the frames its slot requires",
        )
    ]


def grid_alignment(edl: Edl, renders: list[ClipRender]) -> list[Check]:
    """Every cut must land within a frame of a bar line.

    Measured on the frames the clips actually contain, so a truncated or over-long clip moves
    the cut and is caught here rather than passing on the EDL's own arithmetic.
    """
    slot = 0
    for clip in edl.clips:
        if clip.grid_slot != slot:
            return [
                Check(
                    name="grid_alignment",
                    target=clip.candidate_id,
                    status="fail",
                    detail=f"starts at bar {clip.grid_slot}, expected {slot}",
                )
            ]
        slot += clip.bars

    worst = 0.0
    cumulative_frames = 0
    cumulative_bars = 0
    for render in renders:
        cumulative_frames += render.observed_frames
        cumulative_bars += render.clip.bars
        cut_s = cumulative_frames / edl.output.fps
        worst = max(worst, abs(cut_s - cumulative_bars * edl.grid.bar_s))

    status = "pass" if worst <= 1.0 / edl.output.fps else "fail"
    return [
        Check(
            name="grid_alignment",
            target="reel",
            status=status,
            detail=f"worst cut is {worst * 1000:.1f} ms off its bar line over {slot} bars",
        )
    ]


def duration(edl: Edl, requested_s: float) -> Check:
    """The reel should be about as long as was asked for.

    An unfillable slot ends the timeline early (`app/stages/director.py`), and every other
    check stays green on the shortened reel because they only look at the clips that exist.
    """
    actual = sum(c.bars for c in edl.clips) * edl.grid.bar_s
    off_by = actual - requested_s
    status = "pass" if abs(off_by) <= edl.grid.bar_s else "warn"
    return Check(
        name="duration",
        target="reel",
        status=status,
        detail=f"{actual:.1f}s against {requested_s:.1f}s requested ({off_by:+.1f}s)",
    )


def section_straddle(edl: Edl, music: Music) -> list[Check]:
    """No clip may cross a major section boundary.

    Judged against the sections carried in the EDL, which is what the cut was actually built
    from. A hand-set EDL (`hlreel edl --set`) may not match the project's current `music.json`,
    and checking it against sections it was never built from would report a phantom fault.
    """
    majors = _major_starts(edl.music_sections or music.sections)
    offenders = [
        clip.candidate_id
        for clip in edl.clips
        if any(clip.grid_slot < b < clip.grid_slot + clip.bars for b in majors)
    ]
    if not offenders:
        return [
            Check(
                name="section_straddle",
                target="reel",
                status="pass",
                detail=f"{len(majors)} major boundaries respected",
            )
        ]
    return [
        Check(
            name="section_straddle",
            target=", ".join(offenders),
            status="fail",
            detail="clip spans a major section boundary",
        )
    ]


def _major_starts(sections: list[Section]) -> set[int]:
    return {s.bar_start for s in sections if s.level == "major" and s.bar_start > 0}


def material_match(edl: Edl, music: Music) -> Check:
    """Fight material must not appear before the drums arrive.

    Until a detector classifies clips this cannot be verified, and the check says so rather
    than passing on an assumption.
    """
    drumless = music_stage.drumless_bars(music)
    if drumless == 0:
        return Check(
            name="material_match",
            target="reel",
            status="pass",
            detail="no drumless intro to protect",
        )
    early = [c for c in edl.clips if c.grid_slot < drumless]
    if not early:
        return Check(
            name="material_match",
            target="reel",
            status="pass",
            detail=f"no clip sits in the {drumless} drumless bars",
        )
    unclassified = [c for c in early if c.material == "unknown"]
    if not unclassified:
        offenders = [c.candidate_id for c in early if c.material == "action"]
        return Check(
            name="material_match",
            target=", ".join(offenders) or "reel",
            status="fail" if offenders else "pass",
            detail=(
                "fight material before the drums arrive"
                if offenders
                else f"{len(early)} non-fight clip(s) in the drumless intro"
            ),
        )
    return Check(
        name="material_match",
        target=", ".join(c.candidate_id for c in unclassified),
        status="warn",
        detail=(
            f"{len(unclassified)} of {len(early)} clip(s) in the {drumless} drumless bars are "
            "unclassified, so their placement cannot be verified"
        ),
    )


def fade_target(edl: Edl) -> Check:
    """Name the clip the outro fade lands on, so it is seen before the reel is watched."""
    if not edl.clips:
        return Check(name="fade_target", target="reel", status="warn", detail="no clips")
    last = edl.clips[-1]
    if last.material == "action":
        return Check(
            name="fade_target",
            target=last.candidate_id,
            status="warn",
            detail="the outro fade covers a fight clip; a coda belongs here, not the finale",
        )
    status = "pass" if last.material == "non_action" else "warn"
    return Check(
        name="fade_target",
        target=last.candidate_id,
        status=status,
        detail=(
            f"the fade covers {last.candidate_id} from {last.source_id}, material {last.material}"
        ),
    )


def consecutive_setup(edl: Edl) -> Check:
    """Adjacent clips from the same source read as one shot cut into two."""
    repeats = [
        b.candidate_id
        for a, b in zip(edl.clips, edl.clips[1:], strict=False)
        if a.source_id == b.source_id
    ]
    if not repeats:
        return Check(
            name="consecutive_setup", target="reel", status="pass", detail="no repeated sources"
        )
    return Check(
        name="consecutive_setup",
        target=", ".join(repeats),
        status="warn",
        detail="follows a clip from the same source",
    )
