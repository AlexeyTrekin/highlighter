"""Fighter selection, identity tracking and geometry.

The model itself gets one smoke test; everything else here is the logic around it, which is
where the decisions that matter live.
"""

import numpy as np
import pytest

from app import assets
from app.video import detect

FRAME_W, FRAME_H = 1280, 720


def box(x1: float, height_frac: float, width: float = 200.0) -> detect.Box:
    height = height_frac * FRAME_H
    top = (FRAME_H - height) / 2
    return (x1, top, x1 + width, top + height)


def test_fighters_are_the_two_tallest_people():
    """Measured on a real frame: fighters filled 52% and 56% of frame height, spectators
    20-27%."""
    people = [
        (box(100, 0.25), 0.7),
        (box(340, 0.52), 0.88),
        (box(650, 0.27), 0.79),
        (box(1100, 0.56), 0.74),
        (box(880, 0.20), 0.78),
    ]

    chosen = detect.fighters(people, FRAME_H)

    assert len(chosen) == 2
    assert [round(b[0]) for b in chosen] == [340, 1100]


def test_a_bystander_is_not_promoted_when_a_fighter_leaves_frame():
    """Measured on the real footage: spectators run 20-27% of frame height against a 22%
    threshold, so one of them filled the empty slot and "both fighters visible" was true in
    every window of every clip — useless precisely when a fighter walks off."""
    people = [(box(340, 0.54), 0.9), (box(650, 0.26), 0.8), (box(900, 0.24), 0.8)]

    chosen = detect.fighters(people, FRAME_H)

    assert len(chosen) == 1
    assert round(chosen[0][0]) == 340


def test_two_fighters_at_similar_distance_are_both_kept():
    people = [(box(340, 0.52), 0.9), (box(1100, 0.56), 0.9), (box(650, 0.25), 0.8)]

    assert len(detect.fighters(people, FRAME_H)) == 2


def test_people_too_short_to_be_fighters_are_ignored():
    people = [(box(100, 0.15), 0.9), (box(400, 0.18), 0.9), (box(800, 0.21), 0.9)]

    assert detect.fighters(people, FRAME_H) == []


def test_fighters_come_back_ordered_left_to_right():
    people = [(box(900, 0.5), 0.9), (box(200, 0.5), 0.9)]

    chosen = detect.fighters(people, FRAME_H)

    assert chosen[0][0] < chosen[1][0]


def test_tracking_keeps_identity_when_fighters_cross():
    """Left-to-right ordering swaps who is who the moment they pass each other, which would
    scramble per-fighter motion and kit colour."""
    previous = [box(300, 0.5), box(900, 0.5)]
    # They have crossed: the fighter who was on the left is now on the right.
    current = [box(320, 0.5), box(880, 0.5)]
    crossed = [current[1], current[0]]

    assert detect.track(previous, crossed) == current


def test_tracking_leaves_an_uncrossed_pair_alone():
    previous = [box(300, 0.5), box(900, 0.5)]
    current = [box(340, 0.5), box(880, 0.5)]

    assert detect.track(previous, current) == current


def test_tracking_passes_through_when_a_fighter_is_missing():
    assert detect.track([box(300, 0.5), box(900, 0.5)], [box(400, 0.5)]) == [box(400, 0.5)]


def test_gap_is_measured_in_body_heights():
    """Normalising by height is what makes one threshold work on a close shot and a wide one."""
    near = detect.normalised_gap([box(300, 0.5), box(560, 0.5)])
    far = detect.normalised_gap([box(300, 0.5), box(1000, 0.5)])

    assert near is not None and far is not None
    assert near < far


def test_the_same_geometry_at_a_different_scale_gives_the_same_gap():
    small = [box(300, 0.25, width=100), box(430, 0.25, width=100)]
    large = [box(300, 0.50, width=200), box(560, 0.50, width=200)]

    assert detect.normalised_gap(small) == pytest.approx(detect.normalised_gap(large), rel=0.05)


def test_gap_is_none_without_both_fighters():
    assert detect.normalised_gap([box(300, 0.5)]) is None
    assert detect.normalised_gap([]) is None


def test_letterbox_preserves_aspect_ratio():
    """Stretching 16:9 into a square distorts people vertically, and box height is exactly
    what decides who is a fighter."""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    canvas, transform = detect.letterbox(frame)

    assert canvas.shape == (detect.INPUT_SIZE, detect.INPUT_SIZE, 3)
    assert transform.scale == pytest.approx(detect.INPUT_SIZE / 1280)
    assert transform.pad_y > 0 and transform.pad_x == 0


def test_letterbox_maps_a_box_back_to_source_coordinates():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    _, transform = detect.letterbox(frame)

    x, y = transform.to_source(transform.pad_x, transform.pad_y)

    assert (x, y) == pytest.approx((0.0, 0.0))


def test_kit_colours_read_two_bands():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[300:400, 400:500] = (0, 0, 200)
    frame[400:500, 400:500] = (200, 0, 0)

    values = detect.kit_colours(frame, (400, 290, 500, 510))

    assert values is not None and len(values) == 6


def test_kit_colours_refuse_a_box_too_small_to_have_bands():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    assert detect.kit_colours(frame, (10, 10, 20, 25)) is None


@pytest.mark.needs_model
def test_the_model_loads_and_returns_boxes():
    frame = np.full((720, 1280, 3), 120, dtype=np.uint8)

    found = detect.detect_people(frame)

    assert isinstance(found, list)
    for candidate, confidence in found:
        assert len(candidate) == 4
        assert 0.0 <= confidence <= 1.0


@pytest.mark.needs_model
def test_the_registry_asset_verifies_against_its_pin():
    ok, detail = assets.verify(assets.YOLOV8N)

    assert ok, detail
