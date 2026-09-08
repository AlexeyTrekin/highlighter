"""QA checks — including that they fail when they should, not merely pass when all is well."""

from pathlib import Path

import pytest

from app.manifests.edl import Clip, Crop, Edl, Output
from app.manifests.music import Bar, Grid, Music, Section
from app.manifests.qa import overall
from app.stages import qa
from app.stages.render import ClipRender

BAR_S = 2.0
GRID = Grid(bpm=120.0, beat_s=0.5, bar_s=BAR_S, first_downbeat_s=0.0)
FPS = 30
# A default 2-bar clip at BAR_S=2.0s and 30 fps.
FRAMES_PER_CLIP = int(2 * BAR_S * FPS)


def clip(slot: int, bars: int = 2, source: str = "v01", cid: str | None = None) -> Clip:
    return Clip(
        candidate_id=cid or f"c{slot:03d}",
        source_id=source,
        **{"in": 0.0},
        out=bars * BAR_S,
        bars=bars,
        grid_slot=slot,
        section="s1",
        crop=Crop(),
    )


def edl_of(clips: list[Clip]) -> Edl:
    return Edl(
        grid=GRID,
        output=Output(width=320, height=180, fps=30, duration_s=sum(c.bars for c in clips) * BAR_S),
        clips=clips,
    )


def music_of(sections: list[Section], drum_bar: int | None = None) -> Music:
    backends = {} if drum_bar is None else {"drum_onset_s": f"{drum_bar * BAR_S:.4f}"}
    return Music(
        source="track",
        duration_s=60.0,
        grid=GRID,
        sections=sections,
        bars=[
            Bar(index=i, t=i * BAR_S, rms=1.0, low_energy=1.0, high_energy=0.1) for i in range(30)
        ],
        backends=backends,
    )


def render_of(clip_: Clip, brightness: list[float], tail: int = 0) -> ClipRender:
    """A render whose emitted frame count matches what was asked for, unless a test says
    otherwise by overriding `frames`."""
    return ClipRender(
        clip=clip_,
        path=Path("unused.mp4"),
        frames=len(brightness),
        brightness=brightness,
        tail_identical=tail,
    )


def test_brightness_jump_catches_a_flash():
    """One frame out and straight back: the crop-flash signature."""
    frames = render_of(clip(0), [100.0, 101.0, 140.0, 101.0, 100.0])

    result = qa.brightness_jump([frames])

    assert result[0].status == "fail"


def test_brightness_jump_passes_on_smooth_footage():
    frames = render_of(clip(0), [100.0, 103.0, 106.0, 108.0])

    assert qa.brightness_jump([frames])[0].status == "pass"


def test_a_sustained_lighting_change_is_not_a_flash():
    """Real footage: the camera pans into the sky over three frames and stays bright.

    Measured on clip c060 of the first real render — +17.7 then +14.3, the same direction.
    Flagging that failed a good reel.
    """
    frames = render_of(clip(0), [92.9, 110.0, 127.7, 142.0, 155.0, 170.2])

    assert qa.brightness_jump([frames])[0].status == "pass"


def test_a_repeated_flash_reports_several_frames():
    levels = [100.0, 130.0, 100.0, 130.0, 100.0, 130.0, 100.0]

    assert len(qa.spike_frames(levels)) >= 3


def test_frozen_tail_catches_a_repeated_ending():
    result = qa.frozen_tail([render_of(clip(0), [100.0] * 10, tail=4)])

    assert result[0].status == "fail"
    assert "outran the source" in result[0].detail


def full_render(clip_: Clip, frames: int) -> ClipRender:
    """A clip rendered to exactly the frame count its slot asked for."""
    return render_of(clip_, [100.0 + (i % 3) for i in range(frames)])


def test_grid_alignment_fails_on_a_gap_in_the_timeline():
    clips = [clip(0), clip(4)]

    result = qa.grid_alignment(edl_of(clips), [full_render(c, FRAMES_PER_CLIP) for c in clips])

    assert result[0].status == "fail"
    assert "expected 2" in result[0].detail


def test_grid_alignment_passes_on_a_contiguous_timeline():
    clips = [clip(0), clip(2), clip(4)]

    result = qa.grid_alignment(edl_of(clips), [full_render(c, FRAMES_PER_CLIP) for c in clips])

    assert result[0].status == "pass"


def test_grid_alignment_fails_when_a_clip_is_short_of_its_slot():
    """The check that has to look at the rendered frames: a truncated clip drags every later
    cut off the beat, and recomputing the timeline from the EDL would never see it."""
    clips = [clip(0), clip(2), clip(4)]
    renders = [
        full_render(clips[0], FRAMES_PER_CLIP),
        full_render(clips[1], FRAMES_PER_CLIP - 40),
        full_render(clips[2], FRAMES_PER_CLIP),
    ]

    result = qa.grid_alignment(edl_of(clips), renders)

    assert result[0].status == "fail"


def test_frame_budget_catches_a_truncated_clip():
    clips = [clip(0), clip(2)]
    renders = [full_render(clips[0], FRAMES_PER_CLIP), render_of(clips[1], [100.0] * 40)]
    renders[1].frames = FRAMES_PER_CLIP

    result = qa.frame_budget(edl_of(clips), renders)

    assert result[0].status == "fail"
    assert f"40/{FRAMES_PER_CLIP}" in result[0].target


def test_frame_budget_passes_when_every_clip_is_complete():
    clips = [clip(0), clip(2)]

    result = qa.frame_budget(edl_of(clips), [full_render(c, FRAMES_PER_CLIP) for c in clips])

    assert result[0].status == "pass"


def test_duration_warns_when_the_reel_was_truncated():
    """An unfillable slot ends the timeline early; every other check stays green on what's
    left, so this is the only one that notices."""
    short = qa.duration(edl_of([clip(0)]), requested_s=60.0)
    right = qa.duration(edl_of([clip(i * 2) for i in range(15)]), requested_s=60.0)

    assert short.status == "warn"
    assert right.status == "pass"


def test_section_straddle_fails_when_a_clip_crosses_a_major_boundary():
    music = music_of([Section(name="s2", level="major", bar_start=1, bar_end=9, energy=1.0)])

    result = qa.section_straddle(edl_of([clip(0, bars=2)]), music)

    assert result[0].status == "fail"


def test_section_straddle_ignores_minor_boundaries():
    """Minors are preferred cut points, not mandatory ones."""
    music = music_of([Section(name="s1.1", level="minor", bar_start=1, bar_end=9, energy=1.0)])

    result = qa.section_straddle(edl_of([clip(0, bars=2)]), music)

    assert result[0].status == "pass"


def test_material_match_reports_it_cannot_verify_rather_than_passing():
    """Nothing classifies clips yet, so a pass here would be a claim nothing checked."""
    music = music_of([], drum_bar=3)

    result = qa.material_match(edl_of([clip(0), clip(2)]), music)

    assert result.status == "warn"
    assert "unclassified" in result.detail


def test_fade_target_names_the_clip_the_fade_lands_on():
    result = qa.fade_target(edl_of([clip(0), clip(2, cid="c999")]))

    assert result.target == "c999"


def test_consecutive_setup_warns_on_adjacent_clips_from_one_source():
    result = qa.consecutive_setup(edl_of([clip(0, source="v01"), clip(2, source="v01")]))

    assert result.status == "warn"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [(["pass"], "pass"), (["pass", "warn"], "warn"), (["warn", "fail", "pass"], "fail")],
)
def test_overall_status_takes_the_worst(statuses, expected):
    from app.manifests.qa import Check

    checks = [Check(name="n", target="t", status=s, detail="") for s in statuses]

    assert overall(checks) == expected
