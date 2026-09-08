"""Rendered clips are cached by content, not by position.

Caching by slot index would serve the previous EDL's clip at the new slot after a re-cut — a
stale reel that looks freshly rendered.
"""

from pathlib import Path

from app.manifests.edl import Clip, Crop, Output
from app.stages.render import clip_path

OUTPUT = Output(width=1920, height=1080, fps=30, duration_s=60.0)
ROOT = Path("/tmp/render")


def clip(candidate: str = "c001", slot: int = 0, bars: int = 2, in_: float = 1.0) -> Clip:
    return Clip(
        candidate_id=candidate,
        source_id="v01",
        **{"in": in_},
        out=in_ + bars * 2.0,
        bars=bars,
        grid_slot=slot,
        section="s1",
        crop=Crop(),
    )


def test_the_same_clip_maps_to_the_same_file():
    assert clip_path(ROOT, clip(), OUTPUT) == clip_path(ROOT, clip(), OUTPUT)


def test_a_different_candidate_in_the_same_slot_gets_a_different_file():
    """The re-cut case: slot 0 now holds a different clip."""
    assert clip_path(ROOT, clip(candidate="c001"), OUTPUT) != clip_path(
        ROOT, clip(candidate="c002"), OUTPUT
    )


def test_a_changed_in_point_gets_a_different_file():
    assert clip_path(ROOT, clip(in_=1.0), OUTPUT) != clip_path(ROOT, clip(in_=1.5), OUTPUT)


def test_a_changed_length_gets_a_different_file():
    assert clip_path(ROOT, clip(bars=2), OUTPUT) != clip_path(ROOT, clip(bars=3), OUTPUT)


def test_changed_output_settings_get_a_different_file():
    smaller = Output(width=1280, height=720, fps=30, duration_s=60.0)

    assert clip_path(ROOT, clip(), OUTPUT) != clip_path(ROOT, clip(), smaller)


def test_the_name_still_sorts_by_slot():
    """Concat order comes from the EDL, but a sortable name keeps the directory readable."""
    assert clip_path(ROOT, clip(slot=0), OUTPUT).name < clip_path(ROOT, clip(slot=1), OUTPUT).name
