"""`edl.json` — the contract the renderer is a pure function of."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.manifests.base import Manifest
from app.manifests.candidates import Material
from app.manifests.music import Grid, Section

CropMode = Literal["none", "tracked", "fixed"]


class Crop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: CropMode = "none"
    zoom: float = 1.0
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None

    @model_validator(mode="after")
    def _fixed_needs_a_rectangle(self) -> "Crop":
        if self.mode == "fixed" and None in (self.x, self.y, self.w, self.h):
            raise ValueError("crop mode 'fixed' requires x, y, w and h")
        return self


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int
    height: int
    fps: int
    duration_s: float


class Clip(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    candidate_id: str
    source_id: str
    in_: float = Field(alias="in")
    out: float
    bars: int
    grid_slot: int
    section: str
    crop: Crop = Field(default_factory=Crop)
    speed: float = 1.0
    stabilize: bool = True
    # Carried from the candidate so the render-time checks can judge placement without
    # reaching back into `candidates.json`, which the EDL is meant to be independent of.
    material: Material = "unknown"
    target_side: Literal["L", "R"] | None = None
    score: float = 0.0
    order_reason: str = ""
    why: str = ""


class Edl(Manifest):
    stage: str = "director"
    grid: Grid
    music_sections: list[Section] = Field(default_factory=list)
    output: Output
    clips: list[Clip] = Field(default_factory=list)


def slot_seconds(clip: Clip, grid: Grid) -> float:
    """Length of the clip's slot on the music timeline."""
    return clip.bars * grid.bar_s


def source_seconds(clip: Clip, grid: Grid) -> float:
    """Source footage the slot consumes.

    Equal to the slot at speed 1.0; the factor is written out because slow motion breaks the
    identity and the arithmetic must not be simplified away (`spec/008_render.md`).
    """
    return slot_seconds(clip, grid) * clip.speed


def frame_counts(clips: list[Clip], grid: Grid, fps: int) -> list[int]:
    """Output frame count per clip, accumulated rather than rounded independently.

    Rounding each clip alone accumulates error and slides later cuts off the grid, so each
    boundary is rounded once on the cumulative timeline and neighbours share it.
    """
    counts: list[int] = []
    cumulative_bars = 0
    previous_frame = 0
    for clip in clips:
        cumulative_bars += clip.bars
        boundary = round(cumulative_bars * grid.bar_s * fps)
        counts.append(boundary - previous_frame)
        previous_frame = boundary
    return counts
