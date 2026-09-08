"""Material classification and the composite score.

`006_music.md` forbids fight material before the drums arrive, so this is what stops a lunge
landing under a quiet chord.

The discriminator is what the *distance between the fighters* does, not how much motion there
is. Vigour cannot separate the cases: a hug is dynamic and a salute can include a clash.
Fencing closes and breaks repeatedly; an embrace comes together and stays; a salute or a
walk-on holds its distance.
"""

import numpy as np
import pytest

from app.manifests.candidates import Features
from app.manifests.project import ScoringWeights
from app.stages import candidates as stage

WEIGHTS = ScoringWeights()


def features(**kwargs) -> Features:
    """An exchange by default: in measure, swinging, both fighters visible."""
    base = {
        "peak_activity": 12.0,
        "median_sharpness": 400.0,
        "both_visible_frac": 0.9,
        "min_gap": 0.4,
        "closing_speed": 1.0,
        "gap_variation": 0.8,
        "measure_crossings": 3,
    }
    return Features(**{**base, **kwargs})


def test_an_exchange_is_action():
    assert stage.classify(features()) == "action"


def test_a_vigorous_hug_is_not_action():
    """Dynamic, in contact, both visible — but the distance never moves. Activity alone
    cannot tell this from fencing, which is why the rule does not use it."""
    hug = features(peak_activity=22.0, min_gap=-0.2, gap_variation=0.05, measure_crossings=0)

    assert stage.classify(hug) == "non_action"


def test_a_salute_with_a_clash_is_not_action():
    """Blades meet and it is loud, but the pair holds its distance throughout."""
    salute = features(peak_activity=18.0, min_gap=0.9, gap_variation=0.08, measure_crossings=0)

    assert stage.classify(salute) == "non_action"


def test_a_walk_on_with_one_person_is_not_action():
    assert stage.classify(features(both_visible_frac=0.2)) == "non_action"


def test_a_window_that_neither_swings_nor_holds_is_unknown():
    """A real answer, not a placeholder: forcing it is how a fight clip lands under a quiet
    chord with a green check."""
    ambiguous = features(gap_variation=0.45, measure_crossings=0, min_gap=0.9)

    assert stage.classify(ambiguous) == "unknown"


def test_swinging_but_never_in_measure_is_unknown():
    """Moving around at a distance is not an exchange, but it is not calm material either."""
    circling = features(min_gap=1.4, gap_variation=0.9, measure_crossings=0)

    assert stage.classify(circling) == "unknown"


def test_material_is_unknown_when_the_gap_was_never_measurable():
    assert stage.classify(features(gap_variation=None)) == "unknown"


def test_gap_variation_ignores_a_single_bad_detection():
    """One mis-detected box must not make a steady embrace look like an exchange."""
    steady = np.array([0.10, 0.11, 0.09, 0.12, 0.10, 0.11, 0.10])
    with_glitch = np.array([0.10, 0.11, 0.09, 3.00, 0.10, 0.11, 0.10])

    assert stage.gap_variation(with_glitch) == pytest.approx(stage.gap_variation(steady), abs=0.05)


def test_measure_crossings_counts_both_directions():
    gaps = np.array([1.2, 1.1, 0.3, 0.2, 1.0, 1.1, 0.4])

    assert stage.measure_crossings(gaps) == 3


def test_measure_crossings_is_zero_when_the_pair_stays_put():
    assert stage.measure_crossings(np.array([0.1, 0.12, 0.09, 0.11])) == 0
    assert stage.measure_crossings(np.array([1.4, 1.5, 1.3, 1.45])) == 0


def test_a_walk_on_is_proposed_even_though_it_has_no_gap():
    """One person crossing frame is intro material, and stable-gap detection cannot find it:
    measuring a gap needs two fighters, so a solo stretch has no gap to hold steady."""
    from app.manifests.analysis import Analysis, Row
    from app.manifests.project import Source

    pair = [(0.0, 0.0, 100.0, 400.0), (300.0, 0.0, 400.0, 400.0)]
    rows = [
        Row(
            t=i / 6.0,
            boxes=[pair[0]] if 12 <= i < 42 else pair,
            gap=None if 12 <= i < 42 else 0.5,
            activity=1.0,
        )
        for i in range(60)
    ]
    data = Analysis(
        source_id="v01",
        fps=30.0,
        frame_count=300,
        width=1280,
        height=720,
        duration_s=10.0,
        sample_step=5,
        rows=rows,
    )
    source = Source(
        id="v01",
        original_name="v01.mp4",
        path="/tmp/v01.mp4",
        duration_s=10.0,
        fps=30.0,
        width=1280,
        height=720,
        shape="long",
    )

    found = stage.solo_windows(source, data, bar_s=2.0)

    assert len(found) == 1
    assert found[0].origin == "calm"
    assert found[0].end - found[0].start >= 2.0


def test_score_stays_inside_its_contracted_range():
    """`spec/002_manifests.md` promises 0-1, and the benchmark and review UI take it
    literally."""
    extremes = [
        features(),
        features(peak_activity=0.0, closing_speed=None, both_visible_frac=0.0, min_gap=None),
        features(peak_activity=1e6, closing_speed=1e6, median_sharpness=1e9, min_gap=0.0),
    ]

    for candidate in extremes:
        assert 0.0 <= stage.score(candidate, WEIGHTS) <= 1.0


def test_a_committed_attack_outscores_flailing():
    """Same limb motion; only one of them closes. This is the whole point of closing speed."""
    committed = features(peak_activity=14.0, closing_speed=2.0)
    flailing = features(peak_activity=14.0, closing_speed=0.0)

    assert stage.score(committed, WEIGHTS) > stage.score(flailing, WEIGHTS)


def test_a_window_where_a_fighter_is_missing_scores_lower():
    both = features(both_visible_frac=1.0)
    one = features(both_visible_frac=0.3)

    assert stage.score(both, WEIGHTS) > stage.score(one, WEIGHTS)


def test_blurred_footage_scores_lower_than_sharp():
    sharp = features(median_sharpness=600.0)
    blurred = features(median_sharpness=30.0)

    assert stage.score(sharp, WEIGHTS) > stage.score(blurred, WEIGHTS)


def test_weights_actually_change_the_ranking():
    """Weights are configuration precisely so the benchmark can tune them."""
    sharp_but_dull = features(peak_activity=2.0, median_sharpness=900.0, closing_speed=0.0)
    active_but_soft = features(peak_activity=18.0, median_sharpness=40.0, closing_speed=2.0)

    activity_led = ScoringWeights(peak_activity=4.0, median_sharpness=0.1)
    sharpness_led = ScoringWeights(peak_activity=0.1, closing_speed=0.1, median_sharpness=4.0)

    assert stage.score(active_but_soft, activity_led) > stage.score(sharp_but_dull, activity_led)
    assert stage.score(sharp_but_dull, sharpness_led) > stage.score(active_but_soft, sharpness_led)


def test_a_missing_closing_speed_does_not_crash_or_dominate():
    """The pose backend is optional, so null must be handled as "no evidence", not as best or
    worst."""
    absent = stage.score(features(closing_speed=None), WEIGHTS)
    zero = stage.score(features(closing_speed=0.0), WEIGHTS)

    assert absent == pytest.approx(zero)
