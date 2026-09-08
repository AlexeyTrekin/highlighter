"""Where the track's low-energy opening ends.

The rule this feeds — non-fight material there — is about section character, so it is read off
the section table and never off a drum entry: a track may have no drums, no intro, or open at
full energy (`spec/006_music.md`).
"""

import pytest

from app.manifests.music import Bar, Grid, Music, Section
from app.stages import music as music_stage

BAR_S = 1.9969


def music_of(sections: list[Section]) -> Music:
    return Music(
        source="track",
        duration_s=60.0,
        grid=Grid(bpm=120.19, beat_s=BAR_S / 4, bar_s=BAR_S, first_downbeat_s=0.186),
        sections=sections,
        bars=[
            Bar(index=i, t=i * BAR_S, rms=1.0, low_energy=1.0, high_energy=0.1) for i in range(31)
        ],
    )


def test_the_reference_track_gives_the_same_six_bars_the_drum_entry_marked():
    """The section table alone reproduces what the drum onset used to say — its major sections
    sit at 0.44, 1.00 and 0.66 of the peak, and the drums enter at bar 6."""
    reference = [
        Section(name="intro", level="major", bar_start=0, bar_end=5, energy=1.2177),
        Section(name="s1", level="major", bar_start=6, bar_end=27, energy=2.7947),
        Section(name="outro", level="major", bar_start=28, bar_end=30, energy=1.8516),
    ]

    assert music_stage.quiet_opening_bars(music_of(reference)) == 6


def test_a_track_that_opens_loud_has_no_quiet_opening():
    loud = [
        Section(name="s1", level="major", bar_start=0, bar_end=20, energy=9.0),
        Section(name="s2", level="major", bar_start=21, bar_end=30, energy=2.0),
    ]

    assert music_stage.quiet_opening_bars(music_of(loud)) == 0


def test_consecutive_quiet_sections_are_all_part_of_the_opening():
    """A track can ease in over two sections; the preference covers both."""
    eased = [
        Section(name="a", level="major", bar_start=0, bar_end=3, energy=0.5),
        Section(name="b", level="major", bar_start=4, bar_end=7, energy=1.0),
        Section(name="c", level="major", bar_start=8, bar_end=30, energy=9.0),
    ]

    assert music_stage.quiet_opening_bars(music_of(eased)) == 8


def test_a_quiet_section_later_in_the_track_is_not_an_opening():
    """Only the leading run counts — a breakdown in the middle is not an intro."""
    breakdown = [
        Section(name="a", level="major", bar_start=0, bar_end=9, energy=9.0),
        Section(name="b", level="major", bar_start=10, bar_end=30, energy=0.5),
    ]

    assert music_stage.quiet_opening_bars(music_of(breakdown)) == 0


@pytest.mark.parametrize(
    "sections", [[], [Section(name="only", level="major", bar_start=0, bar_end=30, energy=1.0)]]
)
def test_a_track_with_nothing_to_compare_has_no_quiet_opening(sections):
    """One section is its own peak, so it can never be the quiet part of anything."""
    assert music_stage.quiet_opening_bars(music_of(sections)) == 0


def test_minor_sections_carry_the_answer_when_there_are_no_major_ones():
    minor = [
        Section(name="a", level="minor", bar_start=0, bar_end=2, energy=0.5),
        Section(name="b", level="minor", bar_start=3, bar_end=30, energy=9.0),
    ]

    assert music_stage.quiet_opening_bars(music_of(minor)) == 3
