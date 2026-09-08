"""Render and QA end to end on synthetic footage.

This is where the frame loop, the encoder pipe, the resume path and the QA wiring actually
run — every branch of it was previously covered only by reasoning.
"""

import pytest

from app.manifests.edl import Clip, Crop, Edl, Output
from app.manifests.music import Bar, Grid, Music
from app.manifests.project import Options, Project, Source
from app.stages import qa as qa_stage
from app.stages import render as render_stage
from app.video import decode

pytestmark = pytest.mark.needs_ffmpeg

BPM = 120.0
BAR_S = 4 * 60.0 / BPM
FPS = 30
SIZE = (160, 90)
GRID = Grid(bpm=BPM, beat_s=60.0 / BPM, bar_s=BAR_S, first_downbeat_s=0.0)


@pytest.fixture
def source_video(tmp_path, video_factory):
    """Twelve seconds of gently rising brightness — no flashes, no frozen runs."""
    path = video_factory(tmp_path, "src", [40 + (i % 60) for i in range(360)], fps=FPS, size=SIZE)
    return path


def project_for(path) -> Project:
    return Project(
        id="t",
        created_at="2026-09-08T00:00:00+00:00",
        options=Options(duration_s=2 * BAR_S, width=SIZE[0], height=SIZE[1], fps=FPS),
        sources=[
            Source(
                id="v01",
                original_name=path.name,
                path=str(path),
                duration_s=12.0,
                fps=float(FPS),
                width=SIZE[0],
                height=SIZE[1],
                shape="long",
            )
        ],
    )


def edl_for(clips: list[Clip]) -> Edl:
    return Edl(
        grid=GRID,
        output=Output(
            width=SIZE[0],
            height=SIZE[1],
            fps=FPS,
            duration_s=sum(c.bars for c in clips) * BAR_S,
        ),
        clips=clips,
    )


def clip_at(slot: int, in_: float, bars: int = 1, stabilize: bool = False) -> Clip:
    return Clip(
        candidate_id=f"c{slot:03d}",
        source_id="v01",
        **{"in": in_},
        out=in_ + bars * BAR_S,
        bars=bars,
        grid_slot=slot,
        section="s1",
        crop=Crop(mode="none"),
        stabilize=stabilize,
    )


def music_for() -> Music:
    return Music(
        source="procedural",
        duration_s=12.0,
        grid=GRID,
        bars=[
            Bar(index=i, t=i * BAR_S, rms=1.0, low_energy=1.0, high_energy=0.1) for i in range(6)
        ],
    )


def test_render_emits_exactly_the_frames_the_slot_requires(tmp_path, source_video):
    project = project_for(source_video)
    clips = [clip_at(0, 1.0), clip_at(1, 5.0)]
    edl = edl_for(clips)

    renders = render_stage.run(project, edl, tmp_path / "out", tmp_path / "reel.mp4")

    for render in renders:
        assert render.observed_frames == render.frames
    assert sum(r.frames for r in renders) == round(2 * BAR_S * FPS)


def test_a_slot_longer_than_its_source_fails_loudly(tmp_path, source_video):
    """The freeze the prototype shipped: the renderer must refuse, not repeat a frame."""
    project = project_for(source_video)
    edl = edl_for([clip_at(0, 11.0, bars=2)])

    with pytest.raises(decode.SourceExhausted):
        render_stage.run(project, edl, tmp_path / "out", tmp_path / "reel.mp4")


def test_a_failed_clip_leaves_nothing_the_resume_path_would_trust(tmp_path, source_video):
    project = project_for(source_video)
    out = tmp_path / "out"
    edl = edl_for([clip_at(0, 11.0, bars=2)])

    with pytest.raises(decode.SourceExhausted):
        render_stage.run(project, edl, out, tmp_path / "reel.mp4")

    assert list(out.glob("*.mp4")) == []


def test_a_second_run_reuses_the_cached_clip(tmp_path, source_video):
    project = project_for(source_video)
    out = tmp_path / "out"
    edl = edl_for([clip_at(0, 1.0), clip_at(1, 5.0)])

    first = render_stage.run(project, edl, out, tmp_path / "reel.mp4")
    stamps = {r.path: r.path.stat().st_mtime_ns for r in first}
    second = render_stage.run(project, edl, out, tmp_path / "reel2.mp4")

    assert [r.path for r in second] == list(stamps)
    assert all(r.path.stat().st_mtime_ns == stamps[r.path] for r in second)


def test_a_truncated_cached_clip_is_re_rendered(tmp_path, source_video):
    """A non-empty but short file must not satisfy the checkpoint."""
    project = project_for(source_video)
    out = tmp_path / "out"
    edl = edl_for([clip_at(0, 1.0)])

    first = render_stage.run(project, edl, out, tmp_path / "reel.mp4")
    victim = first[0].path
    victim.write_bytes(victim.read_bytes()[: len(victim.read_bytes()) // 3])

    second = render_stage.run(project, edl, out, tmp_path / "reel2.mp4")

    assert second[0].observed_frames == second[0].frames


def test_the_reel_is_produced_and_qa_reads_it(tmp_path, source_video):
    project = project_for(source_video)
    out = tmp_path / "out"
    reel = tmp_path / "reel.mp4"
    edl = edl_for([clip_at(0, 1.0), clip_at(1, 5.0)])

    renders = render_stage.run(project, edl, out, reel)
    report = qa_stage.run(edl, music_for(), renders, project.options.duration_s)

    assert reel.exists() and reel.stat().st_size > 0
    statuses = {c.name: c.status for c in report.checks}
    assert statuses["frame_budget"] == "pass"
    assert statuses["grid_alignment"] == "pass"
    assert statuses["frozen_tail"] == "pass"
    assert statuses["brightness_jump"] == "pass"


def test_stabilisation_path_runs(tmp_path, source_video):
    """libvidstab is a host prerequisite; exercise the two-pass branch rather than assume it."""
    project = project_for(source_video)
    edl = edl_for([clip_at(0, 1.0, stabilize=True)])

    renders = render_stage.run(project, edl, tmp_path / "out", tmp_path / "reel.mp4")

    assert renders[0].path.exists()
    assert not list((tmp_path / "out").glob("*.trf"))
    assert not list((tmp_path / "out").glob("*.raw.mp4"))
