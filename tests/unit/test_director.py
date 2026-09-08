"""Director structure: fillable slots, cuts on musical events, material matching, determinism."""

import pytest

from app.manifests import base
from app.manifests.candidates import Candidate, Candidates
from app.manifests.music import Bar, Grid, Music, Section
from app.manifests.project import Options, Project, Source
from app.stages import director

BAR_S = 4 * 60 / 120.19


def music_with(sections: list[Section], drum_bar: int | None = None) -> Music:
    grid = Grid(bpm=120.19, beat_s=60 / 120.19, bar_s=BAR_S, first_downbeat_s=0.21)
    bars = [
        Bar(index=i, t=0.21 + i * BAR_S, rms=1.0, low_energy=1.0, high_energy=0.1)
        for i in range(30)
    ]
    backends = {}
    if drum_bar is not None:
        backends["drum_onset_s"] = f"{0.21 + drum_bar * BAR_S:.4f}"
    return Music(
        source="track",
        duration_s=30 * BAR_S,
        grid=grid,
        sections=sections,
        bars=bars,
        backends=backends,
    )


def project_with(sources: list[tuple[str, float]], duration_s: float = 24.0) -> Project:
    return Project(
        id="p",
        created_at="2026-09-08T00:00:00+00:00",
        options=Options(duration_s=duration_s),
        sources=[
            Source(
                id=sid,
                original_name=f"{sid}.mp4",
                path=f"/tmp/{sid}.mp4",
                duration_s=length,
                fps=30.0,
                width=1280,
                height=720,
                shape="short" if length <= 9 else "long",
            )
            for sid, length in sources
        ],
    )


def candidates_for(entries: list[tuple[str, str, float, float, str]]) -> Candidates:
    return Candidates(
        candidates=[
            Candidate(
                id=cid,
                source_id=sid,
                start=max(0.0, end - 4.5),
                end=end,
                anchor=end,
                kind="short",
                score=score,
                material=material,  # type: ignore[arg-type]
            )
            for cid, sid, end, score, material in entries
        ]
    )


def test_a_source_too_short_for_a_slot_is_never_placed():
    """v31 held 3.10 s and was given a 4.09 s slot. It must not reach the EDL at all."""
    project = project_with([("v01", 3.10), ("v02", 12.0)])
    candidates = candidates_for(
        [("c001", "v01", 3.10, 99.0, "unknown"), ("c002", "v02", 12.0, 1.0, "unknown")]
    )

    edl = director.run(project, music_with([]), candidates)

    assert "v01" not in {c.source_id for c in edl.clips}
    assert edl.clips, "the usable source should still be placed"


def test_every_clip_can_be_filled_by_its_source():
    project = project_with([("v01", 12.0), ("v02", 9.0), ("v03", 20.0)])
    candidates = candidates_for(
        [
            ("c001", "v01", 12.0, 5.0, "unknown"),
            ("c002", "v02", 9.0, 4.0, "unknown"),
            ("c003", "v03", 20.0, 3.0, "unknown"),
        ]
    )

    edl = director.run(project, music_with([]), candidates)

    by_id = {s.id: s for s in project.sources}
    for clip in edl.clips:
        assert clip.in_ >= -1e-9
        assert clip.out <= by_id[clip.source_id].duration_s + 1e-9
        assert clip.out - clip.in_ == pytest.approx(clip.bars * BAR_S)


def test_no_clip_straddles_a_major_boundary():
    sections = [
        Section(name="intro", level="major", bar_start=0, bar_end=5, energy=0.5),
        Section(name="s1", level="major", bar_start=6, bar_end=29, energy=9.0),
    ]
    project = project_with([(f"v{i:02d}", 20.0) for i in range(1, 8)], duration_s=24.0)
    candidates = candidates_for(
        [(f"c{i:03d}", f"v{i:02d}", 20.0, float(10 - i), "unknown") for i in range(1, 8)]
    )

    edl = director.run(project, music_with(sections), candidates)

    for clip in edl.clips:
        assert not (clip.grid_slot < 6 < clip.grid_slot + clip.bars), (
            f"{clip.candidate_id} spans the boundary at bar 6"
        )


def test_action_material_stays_out_of_the_drumless_intro():
    """v3 put an action clip in the quiet intro; it must now be ineligible there."""
    project = project_with([("v01", 20.0), ("v02", 20.0)], duration_s=12.0)
    candidates = candidates_for(
        [("c001", "v01", 20.0, 99.0, "action"), ("c002", "v02", 20.0, 1.0, "non_action")]
    )

    edl = director.run(project, music_with([], drum_bar=3), candidates)

    early = [c for c in edl.clips if c.grid_slot < 3]
    assert early
    assert all(c.candidate_id == "c002" for c in early)


@pytest.mark.parametrize(
    ("length", "expected"),
    [
        (0, []),
        (1, []),
        (2, [2]),
        (3, [3]),
        (4, [2, 2]),
        (5, [3, 2]),
        (6, [2, 2, 2]),
        (7, [3, 2, 2]),
    ],
)
def test_partition_never_produces_a_slot_no_candidate_could_fill(length, expected):
    """A one-bar slot is shorter than the minimum window, so it must never be planned."""
    assert director.partition(length) == expected
    assert all(bars >= director.MIN_BARS for bars in director.partition(length))
    assert sum(director.partition(length)) in (0, length)


def test_slots_are_contiguous_and_stop_at_major_boundaries():
    sections = [
        Section(name="intro", level="major", bar_start=0, bar_end=5, energy=0.5),
        Section(name="s1", level="major", bar_start=6, bar_end=29, energy=9.0),
    ]
    slots = director.plan_slots(music_with(sections), total_bars=12)

    cursor = 0
    for start, bars in slots:
        assert start == cursor
        cursor += bars
    assert (6, 2) in slots, "a slot must begin exactly at the major boundary"


def test_the_opening_may_be_a_single_bar():
    """The reference track's first musical step is one bar in. Without the opening exception
    that boundary is unusable and the cut falls back to a plain bar carrying no event."""
    sections = [
        Section(name="intro", level="major", bar_start=0, bar_end=5, energy=0.5),
        Section(name="intro.0", level="minor", bar_start=0, bar_end=0, energy=0.3),
        Section(name="intro.1", level="minor", bar_start=1, bar_end=5, energy=0.6),
    ]

    slots = director.plan_slots(music_with(sections), total_bars=6)

    assert slots[0] == (0, 1)
    assert sum(bars for _, bars in slots) == 6
    assert all(bars >= director.MIN_BARS for start, bars in slots if start != 0)


def test_only_the_opening_may_be_short():
    """A one-bar slot mid-reel reads as a mistake, not an opening gesture."""
    sections = [
        Section(name="intro", level="major", bar_start=0, bar_end=7, energy=0.5),
        Section(name="intro.1", level="minor", bar_start=7, bar_end=7, energy=0.6),
    ]

    slots = director.plan_slots(music_with(sections), total_bars=8)

    assert all(bars >= director.MIN_BARS for start, bars in slots if start != 0)
    assert sum(bars for _, bars in slots) == 8


@pytest.mark.parametrize(
    ("length", "minimum", "expected"),
    [(1, 1, [1]), (1, 2, []), (2, 1, [2]), (5, 1, [3, 2]), (6, 2, [2, 2, 2])],
)
def test_partition_respects_the_floor_it_is_given(length, minimum, expected):
    assert director.partition(length, minimum) == expected


def test_a_source_that_only_fills_one_bar_survives_the_gate():
    """Gated at the absolute floor, so a window usable only in the opening is not discarded."""
    project = project_with([("v01", 20.0), ("v02", 2.6)], duration_s=12.0)
    candidates = candidates_for(
        [("c001", "v01", 20.0, 0.5, "unknown"), ("c002", "v02", 2.6, 0.9, "unknown")]
    )
    sections = [
        Section(name="intro", level="major", bar_start=0, bar_end=5, energy=0.5),
        Section(name="intro.0", level="minor", bar_start=0, bar_end=0, energy=0.3),
        Section(name="intro.1", level="minor", bar_start=1, bar_end=5, energy=0.6),
    ]

    edl = director.run(project, music_with(sections), candidates)

    assert edl.clips[0].bars == 1
    assert edl.clips[0].source_id == "v02", "the short source can only fill the opening"


def test_the_director_is_deterministic():
    """Clips must not move between runs; a user cannot tell drift from an improvement."""
    project = project_with([(f"v{i:02d}", 20.0) for i in range(1, 6)])
    # Equal scores would otherwise let iteration order decide.
    candidates = candidates_for(
        [(f"c{i:03d}", f"v{i:02d}", 20.0, 5.0, "unknown") for i in range(1, 6)]
    )
    score = music_with([])

    first = director.run(project, score, candidates)
    second = director.run(project, score, candidates)

    assert base.dumps(first) == base.dumps(second)


def test_every_clip_records_why_it_holds_its_slot():
    project = project_with([("v01", 20.0), ("v02", 20.0)])
    candidates = candidates_for(
        [("c001", "v01", 20.0, 5.0, "unknown"), ("c002", "v02", 20.0, 4.0, "unknown")]
    )

    edl = director.run(project, music_with([]), candidates)

    assert all(clip.order_reason for clip in edl.clips)


def test_no_usable_candidates_is_an_error_not_an_empty_reel():
    """Every window below one bar: nothing survives the gate."""
    project = project_with([("v01", 1.2)])
    candidates = candidates_for([("c001", "v01", 1.2, 5.0, "unknown")])

    with pytest.raises(director.NoUsableCandidates):
        director.run(project, music_with([]), candidates)


def test_an_unfillable_first_slot_is_an_error_not_an_empty_reel():
    """A one-bar window survives the gate but cannot fill a two-bar opening slot. Returning an
    empty EDL would ship a zero-length reel with every check green."""
    project = project_with([("v01", 2.2)])
    candidates = candidates_for([("c001", "v01", 2.2, 5.0, "unknown")])

    with pytest.raises(director.NoUsableCandidates):
        director.run(project, music_with([]), candidates)
