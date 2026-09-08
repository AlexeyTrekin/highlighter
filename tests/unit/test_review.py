"""How the human's decisions reach the edit.

The review step is an override, never a gate: an unvisited project still renders
(`spec/007_review_ui.md`).
"""

import pytest

from app.manifests import review as review_schema
from app.manifests.candidates import Candidate, Candidates
from app.manifests.music import Bar, Grid, Music
from app.manifests.project import Options, Project, Source
from app.manifests.review import Review, Trim
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


def test_a_trim_pulls_the_anchor_back_inside_the_window():
    candidates = Candidates(candidates=[candidate("c001")])
    review = Review(trims={"c001": Trim(start=2.0, end=5.0)})

    applied = director.applied(candidates, review)

    assert applied.candidates[0].anchor <= 5.0


def test_applying_a_review_does_not_mutate_the_original():
    """The director may run more than once; the manifest it was handed must survive it."""
    original = Candidates(candidates=[candidate("c001")])
    review = Review(verdicts={"c001": "drop"}, trims={"c001": Trim(start=3.0, end=7.0)})

    director.applied(original, review)

    assert original.candidates[0].flags == []
    assert original.candidates[0].start == 1.0


def _project_and_music():
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

    Measured while operating the real page: a clip marked keep and then trimmed below the
    shortest slot vanished from the reel without a word.
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


def test_a_keep_on_a_gated_candidate_says_which_gate():
    project, music = _project_and_music()
    blocked = candidate("c002")
    blocked.flags = ["fighters_not_both_visible"]
    candidates = Candidates(candidates=[candidate("c001"), blocked])
    review = Review(verdicts={"c002": "keep"})

    edl = director.run(project, music, candidates, review)
    conflicts = director.unhonoured_keeps(project, music, candidates, review, edl)

    assert conflicts and "fighters_not_both_visible" in conflicts[0][1]


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [({}, 0), ({"c001": "agent"}, 0), ({"c001": "keep"}, 1), ({"c001": "keep", "c002": "drop"}, 2)],
)
def test_touched_counts_only_real_decisions(verdicts, expected):
    """So the agent can say whether the edit was reviewed or chosen for the user."""
    assert review_schema.touched(Review(verdicts=verdicts)) == expected
