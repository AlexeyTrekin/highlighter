"""`music.json` — the timeline every cut is placed on."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.manifests.base import Manifest

SectionLevel = Literal["major", "minor"]
MusicSource = Literal["track", "procedural"]


class Grid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bpm: float
    beat_s: float
    bar_s: float
    first_downbeat_s: float
    beats_per_bar: int = 4


class Section(BaseModel):
    """A stretch of bars sharing a character.

    `level` distinguishes a change of part from a step within one (`spec/006_music.md`).
    Minor sections nest inside major ones and both are present in the same list, so the
    director can cut at a minor boundary without losing the enclosing structure.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    level: SectionLevel
    bar_start: int
    bar_end: int
    energy: float
    arousal: float | None = None
    valence: float | None = None
    mood_tags: list[str] = Field(default_factory=list)


class Bar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    t: float
    rms: float
    low_energy: float
    high_energy: float
    chroma_top: list[int] = Field(default_factory=list)


class Music(Manifest):
    stage: str = "music"
    source: MusicSource
    path: str | None = None
    duration_s: float
    grid: Grid
    sections: list[Section] = Field(default_factory=list)
    chord_change_bars: list[int] = Field(default_factory=list)
    bars: list[Bar] = Field(default_factory=list)
    backends: dict[str, str] = Field(default_factory=dict)


def bar_time(grid: Grid, index: int) -> float:
    """Start of bar `index` on the output timeline."""
    return grid.first_downbeat_s + index * grid.bar_s


def major_sections(music: Music) -> list[Section]:
    return [s for s in music.sections if s.level == "major"]


def section_at_bar(music: Music, index: int) -> Section | None:
    """The innermost section covering `index`, preferring a minor one where they overlap."""
    covering = [s for s in music.sections if s.bar_start <= index <= s.bar_end]
    if not covering:
        return None
    return min(covering, key=lambda s: (s.bar_end - s.bar_start, s.level == "major"))


def major_boundary_bars(music: Music) -> list[int]:
    """Bars at which a major section starts — mandatory cut points."""
    return sorted({s.bar_start for s in major_sections(music)})
