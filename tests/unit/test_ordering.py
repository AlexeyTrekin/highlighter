"""Ordering the user set, and what happens when the reel cannot honour it.

Order only — never a bar. `sequence` and `weights` say which clip comes before which; the slot
plan and the music grid decide which bars each one occupies (`spec/007_review_ui.md`).
"""

import pytest

from app.manifests.candidates import Candidate, Candidates
from app.manifests.music import Bar, Grid, Music, Section
from app.manifests.project import Options, Project, Source
from app.manifests.review import Order, Review
from app.stages import director

BAR_S = 2.0
SOURCES = 12


def project_for(duration_s: float = 24.0) -> Project:
    return Project(
        id="p",
        created_at="2026-09-08T00:00:00+00:00",
        options=Options(duration_s=duration_s),
        sources=[
            Source(
                id=f"v{i:02d}",
                original_name=f"v{i:02d}.mp4",
                path=f"/tmp/v{i:02d}.mp4",
                duration_s=40.0,
                fps=30.0,
                width=1280,
                height=720,
                shape="long",
            )
            for i in range(1, SOURCES + 1)
        ],
    )


def music_for(sections: list[Section] | None = None) -> Music:
    return Music(
        source="track",
        duration_s=80.0,
        grid=Grid(bpm=120.0, beat_s=0.5, bar_s=BAR_S, first_downbeat_s=0.0),
        sections=sections or [],
        bars=[
            Bar(index=i, t=i * BAR_S, rms=1.0, low_energy=1.0, high_energy=0.1) for i in range(40)
        ],
    )


def candidates_for(count: int = SOURCES) -> Candidates:
    """Interchangeable windows, descending in score, one per source.

    Nothing here distinguishes them but the score, so any order that is not score order is the
    user's doing.
    """
    return Candidates(
        candidates=[
            Candidate(
                id=f"c{i:03d}",
                source_id=f"v{i:02d}",
                start=0.0,
                end=30.0,
                anchor=30.0,
                kind="long",
                score=1.0 - i * 0.01,
                material="unknown",
            )
            for i in range(1, count + 1)
        ]
    )


def reel(review: Review, duration_s: float = 24.0, count: int = SOURCES) -> list[str]:
    edl = director.run(project_for(duration_s), music_for(), candidates_for(count), review)
    return [clip.candidate_id for clip in edl.clips]


def test_auto_is_score_order_and_nothing_else():
    assert reel(Review())[:3] == ["c001", "c002", "c003"]


def test_a_strict_sequence_places_its_clips_in_that_order():
    order = Order(mode="strict", sequence=["c009", "c004", "c007"])

    assert reel(Review(order=order))[:3] == ["c009", "c004", "c007"]


def test_a_strict_sequence_need_not_cover_the_reel():
    """ "The director places only the clips left to it" — the rest follows its own rules."""
    placed = reel(Review(order=Order(mode="strict", sequence=["c009"])))

    assert placed[0] == "c009"
    assert placed[1:3] == ["c001", "c002"]


def test_a_pinned_clip_is_not_spent_on_an_earlier_slot():
    """Otherwise the highest-scoring clip in the pool fills slot 0 and the pin at slot 2 finds
    its clip already used."""
    order = Order(mode="strict", sequence=["c003", "c002", "c001"])

    assert reel(Review(order=order))[:3] == ["c003", "c002", "c001"]


def test_the_lowest_weight_opens_and_the_highest_closes():
    order = Order(mode="weighted", weights={"c010": 0.0, "c011": 100.0})
    placed = reel(Review(order=order))

    assert placed[0] == "c010"
    assert placed[-1] == "c011"


def test_unweighted_clips_are_placed_between_the_extremes():
    order = Order(mode="weighted", weights={"c010": 0.0, "c011": 100.0})
    placed = reel(Review(order=order))

    assert "c010" not in placed[1:]
    assert "c011" not in placed[:-1]
    assert len(placed) > 2, "the director still fills the middle"


def test_the_buckets_do_the_same_job_as_the_two_end_weights():
    by_bucket = reel(Review(order=Order(mode="weighted", opening=["c010"], ending=["c011"])))
    by_weight = reel(Review(order=Order(mode="weighted", weights={"c010": 0.0, "c011": 100.0})))

    assert by_bucket == by_weight


def test_free_positions_are_shared_in_proportion_to_the_weight_gaps():
    """A relative composition, not a slot number: 10 → 50 takes about twice the room of
    50 → 70."""
    weights = [10.0, 50.0, 70.0]

    assert director._share_free_slots(weights, free=9) == [6, 3]


@pytest.mark.parametrize("free", [0, 1, 5, 9, 17])
def test_the_shared_positions_always_add_up_to_what_was_available(free):
    """Largest remainder, so nothing is lost to rounding and the reel has no hole in it."""
    shares = director._share_free_slots([0.0, 25.0, 30.0, 100.0], free=free)

    assert sum(shares) == free
    assert all(share >= 0 for share in shares)


def test_equal_weights_are_a_batch_the_director_orders_within():
    """ "These three go early" is what the user said; which of the three comes first is not."""
    order = Order(mode="weighted", weights={"c009": 20.0, "c004": 20.0, "c007": 20.0})
    placed = reel(Review(order=order))

    batch = [cid for cid in placed if cid in {"c004", "c007", "c009"}]
    assert len(batch) == 3
    positions = [placed.index(cid) for cid in batch]
    assert positions == list(range(positions[0], positions[0] + 3)), "the batch stays together"
    assert batch == ["c004", "c007", "c009"], "and falls in the director's own order"


def test_a_single_weight_anchors_proportionally():
    """With nothing to bracket, one weight is read as a place on the axis."""
    placed = reel(Review(order=Order(mode="weighted", weights={"c012": 50.0})))

    assert placed.index("c012") == pytest.approx(len(placed) // 2, abs=1)


def test_the_order_does_not_depend_on_how_the_weights_were_typed():
    """A batch is ordered by the director, and "by the director" must not mean "by whichever key
    the user set first" — a clip that moves between runs for no visible reason is drift the user
    cannot tell from an improvement (`spec/002_manifests.md`)."""
    one_way = Review(order=Order(mode="weighted", weights={"c009": 20.0, "c004": 20.0}))
    the_other = Review(order=Order(mode="weighted", weights={"c004": 20.0, "c009": 20.0}))

    assert reel(one_way) == reel(the_other)


def test_a_pin_overrides_the_quality_gates():
    """Pointing at a clip and saying where it goes says at least as much as keeping it."""
    candidates = candidates_for()
    candidates.candidates[5].flags = ["fighters_not_both_visible"]
    review = Review(order=Order(mode="strict", sequence=["c006"]))

    edl = director.run(project_for(), music_for(), candidates, review)

    assert edl.clips[0].candidate_id == "c006"


def test_a_pin_the_bar_grid_cannot_honour_is_reported():
    """The one thing a pin cannot override: a window too short for the slot would drag every
    later cut off the beat."""
    candidates = candidates_for()
    candidates.candidates[5].end = 1.0  # under a single bar
    review = Review(order=Order(mode="strict", sequence=["c006"]))

    edl = director.run(project_for(), music_for(), candidates, review)
    conflicts = director.unhonoured_keeps(project_for(), music_for(), candidates, review, edl)

    assert "c006" not in {clip.candidate_id for clip in edl.clips}
    assert conflicts and conflicts[0][0] == "c006"
    assert "shortest slot" in conflicts[0][1]


def test_pinning_and_dropping_the_same_clip_is_reported_as_the_contradiction_it_is():
    review = Review(verdicts={"c006": "drop"}, order=Order(mode="strict", sequence=["c006"]))
    candidates = candidates_for()

    edl = director.run(project_for(), music_for(), candidates, review)
    conflicts = director.unhonoured_keeps(project_for(), music_for(), candidates, review, edl)

    assert conflicts == [("c006", "asked for and dropped in the same review")]


def test_a_pin_past_the_end_of_the_reel_says_how_long_the_reel_is():
    """ "Beaten to the last slot" would send the user looking for a competitor; there is none,
    the reel simply stops before that position."""
    review = Review(order=Order(mode="strict", sequence=[f"c{i:03d}" for i in range(1, 12)]))
    candidates = candidates_for()
    # Eight seconds of reel, so four bars and two slots, and nine of the eleven pins have
    # nowhere to go.
    music = music_for()
    project = project_for(duration_s=8.0)

    edl = director.run(project, music, candidates, review)
    conflicts = director.unhonoured_keeps(project, music, candidates, review, edl)

    assert [cid for cid, _ in conflicts] == [f"c{i:03d}" for i in range(3, 12)]
    assert all("holds 2 clips" in reason for _, reason in conflicts)


def test_an_honoured_order_reports_nothing():
    review = Review(order=Order(mode="weighted", weights={"c010": 0.0, "c011": 100.0}))
    candidates = candidates_for()

    edl = director.run(project_for(), music_for(), candidates, review)

    assert director.unhonoured_keeps(project_for(), music_for(), candidates, review, edl) == []


def test_the_edl_records_which_pin_placed_a_clip():
    """`order_reason` justifies the clip's position (`spec/002_manifests.md`), and "the user
    put it there" is the whole justification."""
    review = Review(order=Order(mode="strict", sequence=["c009"]))

    edl = director.run(project_for(), music_for(), candidates_for(), review)

    assert edl.clips[0].order_reason == "pinned by the user, 1 in their sequence"


def test_a_pin_slides_to_the_next_slot_it_fits_rather_than_losing_its_place():
    """Slots are one, two or three bars. Binding the slot number instead of the order drops a
    clip out of the sequence entirely the moment the lengths do not cooperate — measured on the
    real project, where a clip pinned second came out fourth with nothing said."""
    sections = [
        # A three-bar slot second, which the short clip cannot fill.
        Section(name="a", level="major", bar_start=0, bar_end=0, energy=5.0),
        Section(name="b", level="major", bar_start=1, bar_end=39, energy=5.0),
    ]
    candidates = candidates_for()
    candidates.candidates[1].end = 5.0  # two bars' worth, so the three-bar slot is out of reach
    review = Review(order=Order(mode="strict", sequence=["c001", "c002", "c003"]))
    project = project_for()

    edl = director.run(project, music_for(sections), candidates, review)
    placed = [clip.candidate_id for clip in edl.clips]

    assert placed.index("c001") < placed.index("c002") < placed.index("c003")
    assert director.unhonoured_keeps(project, music_for(sections), candidates, review, edl) == []


def test_a_pin_nothing_can_hold_does_not_block_the_rest_of_the_sequence():
    """One impossible clip at the head of the queue must not take the whole order with it."""
    candidates = candidates_for()
    candidates.candidates[0].end = 1.0  # shorter than any slot
    review = Review(order=Order(mode="strict", sequence=["c001", "c002", "c003"]))
    project = project_for()

    edl = director.run(project, music_for(), candidates, review)
    placed = [clip.candidate_id for clip in edl.clips]

    assert placed[:2] == ["c002", "c003"]
    conflicts = director.unhonoured_keeps(project, music_for(), candidates, review, edl)
    assert [cid for cid, _ in conflicts] == ["c001"]


def _one_bar_opening() -> list[Section]:
    """A reel whose first slot is one bar and whose second is three."""
    return [
        Section(name="a", level="major", bar_start=0, bar_end=0, energy=5.0),
        Section(name="b", level="major", bar_start=1, bar_end=39, energy=5.0),
    ]


def test_a_pin_that_gives_up_its_turn_says_that_and_not_that_it_was_beaten():
    """It fits the one-bar opening, which was passed over precisely to honour its own place in
    the order. Telling the user it was "beaten to the last slot" sends them hunting a competitor
    that never existed."""
    candidates = candidates_for()
    candidates.candidates[1].end = 3.0  # one bar's worth: too short for every slot after the first
    review = Review(order=Order(mode="strict", sequence=["c001", "c002"]))
    project, music = project_for(), music_for(_one_bar_opening())

    edl = director.run(project, music, candidates, review)
    conflicts = director.unhonoured_keeps(project, music, candidates, review, edl)

    assert "c002" not in {clip.candidate_id for clip in edl.clips}
    assert conflicts == [
        ("c002", "no slot from its place in your order onwards is short enough for it")
    ]


def test_a_held_back_pin_is_brought_forward_rather_than_ending_the_reel():
    """Withholding a clip until its turn must not cost the whole rest of the reel: the user can
    judge a clip that came early, not footage that was never shown (`spec/006_music.md`).

    Two clips over three slots, the second weighted to the end — so the middle slot has nothing
    but the clip being held back for the last one.
    """
    candidates = candidates_for(count=2)
    review = Review(order=Order(mode="weighted", weights={"c002": 100.0}))
    project, music = project_for(duration_s=12.0), music_for()

    edl = director.run(project, music, candidates, review)

    assert [clip.candidate_id for clip in edl.clips] == ["c001", "c002"]
    assert edl.clips[1].order_reason.startswith("brought forward")
    assert director.unhonoured_keeps(project, music, candidates, review, edl) == []


def test_the_pin_reason_uses_the_users_own_numbering():
    """A clip pinned second can land third because the second slot was too long for it. Saying
    "3 in their order" would describe a request nobody made."""
    candidates = candidates_for()
    candidates.candidates[1].end = 5.0  # skips the three-bar slot
    review = Review(order=Order(mode="strict", sequence=["c001", "c002"]))

    edl = director.run(project_for(), music_for(_one_bar_opening()), candidates, review)
    by_id = {clip.candidate_id: clip for clip in edl.clips}

    assert by_id["c002"].order_reason == "pinned by the user, 2 in their sequence"
    assert by_id["c002"].grid_slot > edl.clips[1].grid_slot, "and it did land later than second"


def test_a_weighted_pin_names_its_weight():
    review = Review(order=Order(mode="weighted", weights={"c009": 30.0}))

    edl = director.run(project_for(), music_for(), candidates_for(), review)
    placed = next(c for c in edl.clips if c.candidate_id == "c009")

    assert placed.order_reason == "pinned by the user at weight 30"


def test_a_rescued_pin_records_the_gate_it_overrode():
    candidates = candidates_for()
    candidates.candidates[5].flags = ["fighters_not_both_visible"]
    review = Review(order=Order(mode="strict", sequence=["c006"]))

    edl = director.run(project_for(), music_for(), candidates, review)

    assert "kept despite fighters_not_both_visible" in edl.clips[0].order_reason
