"""How the human's decisions reach the edit.

The review step is an override, never a gate: an unvisited project still renders
(`spec/007_review_ui.md`).
"""

import pytest

from app.manifests import review as review_schema
from app.manifests.candidates import Candidate, Candidates
from app.manifests.edl import Edl, Output
from app.manifests.music import Bar, Grid, Music, Section
from app.manifests.project import Options, Project, Source
from app.manifests.review import Order, Review, Trim
from app.stages import director


def candidate(cid: str, score: float = 0.5) -> Candidate:
    return Candidate(
        id=cid, source_id=f"v{cid[-2:]}", start=1.0, end=9.0, anchor=9.0, kind="long", score=score
    )


def test_an_untouched_candidate_is_left_to_the_agent():
    assert review_schema.verdict_for(Review(), "c001") == "agent"


def test_an_empty_review_changes_nothing():
    candidates = Candidates(candidates=[candidate("c001"), candidate("c002")])

    applied = director.applied(candidates, Review())

    assert [c.flags for c in applied.candidates] == [[], []]
    assert [c.start for c in applied.candidates] == [1.0, 1.0]


def test_a_dropped_candidate_is_flagged_not_deleted():
    """Nothing is removed, so the decision stays auditable and reversible."""
    candidates = Candidates(candidates=[candidate("c001")])
    review = Review(verdicts={"c001": "drop"})

    applied = director.applied(candidates, review)

    assert len(applied.candidates) == 1
    assert "dropped_by_user" in applied.candidates[0].flags


def test_a_trim_replaces_the_window():
    candidates = Candidates(candidates=[candidate("c001")])
    review = Review(trims={"c001": Trim(start=3.0, end=7.0)})

    applied = director.applied(candidates, review)

    assert (applied.candidates[0].start, applied.candidates[0].end) == (3.0, 7.0)


@pytest.mark.parametrize("trim", [Trim(start=2.0, end=5.0), Trim(start=6.0, end=8.0)])
def test_a_trim_pulls_the_anchor_inside_the_window(trim):
    candidates = Candidates(candidates=[candidate("c001")])

    applied = director.applied(candidates, Review(trims={"c001": trim}))

    assert trim.start <= applied.candidates[0].anchor <= trim.end


def test_applying_a_review_does_not_mutate_the_original():
    """The director may run more than once; the manifest it was handed must survive it."""
    original = Candidates(candidates=[candidate("c001")])
    review = Review(verdicts={"c001": "drop"}, trims={"c001": Trim(start=3.0, end=7.0)})

    director.applied(original, review)

    assert original.candidates[0].flags == []
    assert original.candidates[0].start == 1.0


def _project_and_music(drum_bar: int | None = None, minor_at: int | None = None):
    project = Project(
        id="p",
        created_at="2026-09-08T00:00:00+00:00",
        options=Options(duration_s=12.0),
        sources=[
            Source(
                id=f"v{i:02d}",
                original_name=f"v{i:02d}.mp4",
                path=f"/tmp/v{i:02d}.mp4",
                duration_s=20.0,
                fps=30.0,
                width=1280,
                height=720,
                shape="long",
            )
            for i in (1, 2)
        ],
    )
    bar_s = 2.0
    music = Music(
        source="track",
        duration_s=40.0,
        grid=Grid(bpm=120.0, beat_s=0.5, bar_s=bar_s, first_downbeat_s=0.0),
        bars=[
            Bar(index=i, t=i * bar_s, rms=1.0, low_energy=1.0, high_energy=0.1) for i in range(20)
        ],
        backends={} if drum_bar is None else {"drum_onset_s": f"{drum_bar * bar_s:.4f}"},
        # A minor boundary one bar in is what lets the reel open with a single-bar slot
        # (`spec/006_music.md`), which is the only slot short material can reach.
        sections=[]
        if minor_at is None
        else [
            Section(name="intro", level="minor", bar_start=0, bar_end=minor_at, energy=0.1),
            Section(name="body", level="minor", bar_start=minor_at, bar_end=20, energy=1.0),
        ],
    )
    return project, music


def test_a_kept_clip_outranks_a_better_scoring_one():
    """The user watched the footage; the score is a proxy for that and loses to it."""
    project, music = _project_and_music()
    candidates = Candidates(candidates=[candidate("c001", score=0.9), candidate("c002", score=0.1)])

    without = director.run(project, music, candidates, Review())
    with_keep = director.run(project, music, candidates, Review(verdicts={"c002": "keep"}))

    assert without.clips[0].candidate_id == "c001"
    assert with_keep.clips[0].candidate_id == "c002"


def test_a_keep_that_cannot_be_honoured_is_reported():
    """A keep is the strongest signal the pipeline gets. One that quietly fails to appear is
    the worst outcome available: a decision was made, the reel ignored it, nothing said so.
    """
    project, music = _project_and_music()
    candidates = Candidates(candidates=[candidate("c001", score=0.9), candidate("c002", score=0.5)])
    # Trimmed under one bar, so it can fill no slot at all.
    review = Review(verdicts={"c002": "keep"}, trims={"c002": Trim(start=1.0, end=2.2)})

    edl = director.run(project, music, candidates, review)
    conflicts = director.unhonoured_keeps(project, music, candidates, review, edl)

    assert [cid for cid, _ in conflicts] == ["c002"]
    assert "shortest slot" in conflicts[0][1]


def test_a_honoured_keep_reports_nothing():
    project, music = _project_and_music()
    candidates = Candidates(candidates=[candidate("c001"), candidate("c002")])
    review = Review(verdicts={"c002": "keep"})

    edl = director.run(project, music, candidates, review)

    assert director.unhonoured_keeps(project, music, candidates, review, edl) == []


def test_a_keep_rescues_a_candidate_the_gates_dropped():
    """The gates are a guess about what a viewer would reject; a viewer who looked at the clip
    outranks them (`spec/007_review_ui.md`)."""
    project, music = _project_and_music()
    blocked = candidate("c002")
    blocked.flags = ["fighters_not_both_visible"]
    candidates = Candidates(candidates=[candidate("c001"), blocked])
    review = Review(verdicts={"c002": "keep"})

    edl = director.run(project, music, candidates, review)

    assert edl.clips[0].candidate_id == "c002"
    assert "fighters_not_both_visible" in edl.clips[0].order_reason, "the override is on record"
    assert director.unhonoured_keeps(project, music, candidates, review, edl) == []


def test_a_keep_too_short_for_any_slot_says_so():
    """ "Beaten to the last slot" on a clip no slot could ever have taken sends the user looking
    for a competitor that does not exist."""
    project, music = _project_and_music()
    short = candidate("c002")
    short.end = 3.0  # a single bar, in a reel whose shortest slot is two
    candidates = Candidates(candidates=[candidate("c001"), short])
    review = Review(verdicts={"c002": "keep"})

    edl = director.run(project, music, candidates, review)
    conflicts = director.unhonoured_keeps(project, music, candidates, review, edl)

    assert conflicts == [
        ("c002", "fills none of this reel's slots; the shortest is 2 bars (4.00s)")
    ]


def test_a_gated_candidate_nobody_rescued_stays_out():
    project, music = _project_and_music()
    blocked = candidate("c002")
    blocked.flags = ["fighters_not_both_visible"]
    candidates = Candidates(candidates=[candidate("c001"), blocked])

    edl = director.run(project, music, candidates, Review())

    assert {clip.candidate_id for clip in edl.clips} == {"c001"}


def test_a_trim_binds_even_where_the_window_runs_past_the_file():
    """A trim is a statement about which seconds to use. The clip ends where the file does, so
    a trim measured against the window alone would reach back past its own start."""
    project, music = _project_and_music()
    short = candidate("c001")
    short.end = 24.0  # the source is 20 s; the window over-reaches it
    review = Review(verdicts={"c001": "keep"}, trims={"c001": Trim(start=19.0, end=23.0)})
    candidates = Candidates(candidates=[short])

    with pytest.raises(director.NoUsableCandidates):
        director.run(project, music, candidates, review)

    empty = Edl(
        grid=music.grid,
        output=Output(width=1280, height=720, fps=30.0, duration_s=0.0),
        clips=[],
    )
    conflicts = director.unhonoured_keeps(project, music, candidates, review, empty)
    assert "only 1.00s after trimming" in conflicts[0][1]


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        (Order(), []),
        (Order(mode="strict", sequence=["c001"]), ["mode strict", "1 sequence"]),
        (Order(opening=["c001"], weights={"c002": 2.0}), ["1 opening", "1 weights"]),
    ],
)
def test_ordering_hints_name_what_was_asked_for(order, expected):
    """Recorded but not honoured until WAL 3.2, so `hlreel run` can say so rather than let a
    pinned position fail as silently as an unhonoured keep."""
    assert review_schema.ordering_hints(Review(order=order)) == expected


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [({}, 0), ({"c001": "agent"}, 0), ({"c001": "keep"}, 1), ({"c001": "keep", "c002": "drop"}, 2)],
)
def test_touched_counts_only_real_decisions(verdicts, expected):
    """So the agent can say whether the edit was reviewed or chosen for the user."""
    assert review_schema.touched(Review(verdicts=verdicts)) == expected
