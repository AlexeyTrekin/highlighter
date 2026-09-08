"""End-to-end: ingest a synthetic project, fit the grid, gate candidates, build an EDL.

Render is exercised separately; these checks are about the manifests agreeing with each other
and with the structural rules the prototype broke.
"""

import pytest

from app import pipeline
from app import project as project_store
from app.audio import grid as grid_fit
from app.manifests import base
from app.manifests.candidates import Candidates
from app.manifests.edl import Edl
from app.manifests.project import Options, Project
from app.stages import ingest as ingest_stage
from app.stages import music as music_stage

pytestmark = pytest.mark.needs_ffmpeg

BPM = 120.0
BAR_S = 4 * 60.0 / BPM


@pytest.fixture
def prepared(tmp_path, video_factory, track_factory):
    """A project with a known track and sources of deliberately mixed usability."""
    media = tmp_path / "media"
    media.mkdir()
    # Long enough for several bars, one 24 fps source, and one too short to fill a slot.
    video_factory(media, "a_long", list(range(40, 240, 2)) * 2, fps=30)
    video_factory(media, "b_long", list(range(60, 220, 2)) * 2, fps=24)
    video_factory(media, "c_mid", list(range(30, 200, 3)), fps=30)
    video_factory(media, "d_tiny", [90] * 15, fps=30)

    track = track_factory(tmp_path / "track.wav", bpm=BPM, bars=16, drums_from_bar=4)

    root = tmp_path / "project"
    project = Project(
        id="test",
        created_at=project_store.now(),
        music_path=str(track),
        options=Options(duration_s=20.0, width=320, height=180, fps=30),
    )
    project_store.create(root, project)
    project = ingest_stage.run(project, [media])
    project_store.save(root, project)
    return root, project


def test_ingest_names_sources_in_sorted_order(prepared):
    _, project = prepared

    assert [s.id for s in project.sources] == ["v01", "v02", "v03", "v04"]
    assert [s.original_name for s in project.sources] == sorted(
        s.original_name for s in project.sources
    )


def test_grid_recovers_the_synthetic_tempo(prepared):
    root, project = prepared

    music = pipeline.run_music(root, project)

    assert music.grid.bpm == pytest.approx(BPM, rel=0.05)
    assert music.grid.bar_s == pytest.approx(BAR_S, rel=0.05)


def test_drum_entry_lands_on_a_bar_line(prepared):
    """The phase anchor must put a bar line where the kit arrives."""
    root, project = prepared

    music = pipeline.run_music(root, project)

    onset = music_stage.drum_onset_s(music)
    assert onset is not None
    assert abs(grid_fit.alignment_error(music.grid, onset)) < 1.0 / 30


def test_short_sources_are_gated_out(prepared):
    root, project = prepared
    pipeline.run_music(root, project)

    found = pipeline.run_candidates(root, project)

    tiny = [c for c in found.candidates if c.source_id == "v04"]
    assert tiny, "the short source should still produce a recorded candidate"
    assert all("source_too_short" in c.flags for c in tiny)


def test_edl_is_contiguous_and_every_clip_fits_its_source(prepared):
    root, project = prepared
    pipeline.run_music(root, project)
    pipeline.run_candidates(root, project)

    edl = pipeline.run_director(root, project)

    by_id = {s.id: s for s in project.sources}
    cursor = 0
    for clip in edl.clips:
        assert clip.grid_slot == cursor
        cursor += clip.bars
        assert clip.bars >= 2
        assert clip.in_ >= -1e-9
        assert clip.out <= by_id[clip.source_id].duration_s + 1e-9
    assert "v04" not in {c.source_id for c in edl.clips}


def test_rerunning_the_director_produces_an_identical_edl(prepared):
    root, project = prepared
    pipeline.run_music(root, project)
    pipeline.run_candidates(root, project)

    first = base.dumps(pipeline.run_director(root, project))
    second = base.dumps(pipeline.run_director(root, project))

    assert first == second


def test_manifests_round_trip_through_disk(prepared):
    root, project = prepared
    pipeline.run_music(root, project)
    pipeline.run_candidates(root, project)
    pipeline.run_director(root, project)

    reloaded = base.read(project_store.edl_path(root), Edl)
    candidates = base.read(project_store.candidates_path(root), Candidates)

    assert reloaded.clips
    assert candidates.candidates
    assert reloaded.schema_version == 1


def test_a_completed_stage_is_skipped_without_force(prepared):
    root, project = prepared

    first = pipeline.run(root, project, ("music",), force=False)
    second = pipeline.run(root, project, ("music",), force=False)

    assert first == ["music"]
    assert second == []


def test_a_locked_project_refuses_a_second_writer(prepared):
    root, _ = prepared
    project_store.acquire_lock(root)
    try:
        with pytest.raises(RuntimeError, match="locked"):
            project_store.acquire_lock(root)
    finally:
        project_store.release_lock(root)
