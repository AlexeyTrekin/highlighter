"""Hierarchical section detection.

The reference track steps x1.7 in the sub band as subtle drums enter and x43 as the kit
arrives. A listener hears both, so both must survive detection.
"""

from app.audio import sections
from app.manifests.music import Bar


def bars(low_energies: list[float]) -> list[Bar]:
    return [
        Bar(index=i, t=i * 2.0, rms=low + 1.0, low_energy=low, high_energy=low / 10)
        for i, low in enumerate(low_energies)
    ]


def test_a_loud_transition_does_not_mask_a_subtle_one():
    """The defect this rule exists for: one threshold finds x43 and is deaf to x1.7."""
    found = sections.boundary_bars(bars([0.49, 0.84, 1.04, 1.19, 1.14, 1.51, 66.0, 66.7]))

    assert found[1] == "minor"
    assert found[6] == "major"


def test_boundaries_are_found_in_both_directions():
    """Drums leaving is as much a boundary as drums arriving."""
    found = sections.boundary_bars(bars([1.0, 60.0, 61.0, 2.0]))

    assert found[1] == "major"
    assert found[3] == "major"


def test_minor_sections_nest_inside_their_major_parent():
    built = sections.build_sections(bars([0.49, 0.84, 1.04, 1.19, 1.14, 1.51, 66.0, 66.7, 70.0]))

    majors = [s for s in built if s.level == "major"]
    minors = [s for s in built if s.level == "minor"]

    assert [(s.bar_start, s.bar_end) for s in majors] == [(0, 5), (6, 8)]
    assert any(s.bar_start == 0 and s.bar_end == 0 for s in minors)
    assert all(
        any(m.bar_start <= s.bar_start and s.bar_end <= m.bar_end for m in majors) for s in minors
    )


def test_sections_are_named_positionally():
    """A functional label the baseline cannot determine would be a guess."""
    built = sections.build_sections(bars([1.0, 1.0, 60.0, 60.0, 2.0, 2.0]))
    names = [s.name for s in built if s.level == "major"]

    assert names[0] == "intro"
    assert names[-1] == "outro"
    assert all(n in {"intro", "outro"} or n.startswith("s") for n in names)


def test_a_flat_track_has_one_section():
    built = sections.build_sections(bars([1.0, 1.02, 0.99, 1.01]))

    assert len(built) == 1
    assert built[0].level == "major"


def test_chord_changes_track_the_dominant_pitch_classes():
    rows = bars([1.0, 1.0, 1.0])
    rows[0].chroma_top = [0, 4, 7]
    rows[1].chroma_top = [0, 4, 7]
    rows[2].chroma_top = [2, 5, 9]

    assert sections.chord_change_bars(rows) == [2]
