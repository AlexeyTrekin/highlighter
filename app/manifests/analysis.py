"""`analysis/vNN.json` — per-sampled-frame features for one source."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.manifests.base import Manifest

Box = tuple[float, float, float, float]


class Row(BaseModel):
    """One sampled frame."""

    model_config = ConfigDict(extra="forbid")

    t: float
    boxes: list[Box] = Field(default_factory=list)
    kits: list[list[float] | None] = Field(default_factory=list)
    motion_in: float = 0.0
    motion_out: float = 0.0
    activity: float = 0.0
    gap: float | None = None
    sharpness: float = 0.0
    brightness: float = 0.0


class Analysis(Manifest):
    stage: str = "analyze"
    source_id: str
    fps: float
    frame_count: int
    width: int
    height: int
    duration_s: float
    sample_step: int
    rows: list[Row] = Field(default_factory=list)


def times(analysis: Analysis) -> np.ndarray:
    return np.array([row.t for row in analysis.rows], dtype=float)


def activity(analysis: Analysis) -> np.ndarray:
    return np.array([row.activity for row in analysis.rows], dtype=float)


def recompensate(analysis: Analysis, k: float) -> np.ndarray:
    """Activity recomputed with a different camera coefficient.

    `motion_out` is kept in the manifest precisely so the compensation can be revisited
    without decoding the video again (`spec/002_manifests.md`).
    """
    inside = np.array([row.motion_in for row in analysis.rows], dtype=float)
    outside = np.array([row.motion_out for row in analysis.rows], dtype=float)
    return np.maximum(0.0, inside - k * outside)


def both_visible(analysis: Analysis) -> np.ndarray:
    return np.array([len(row.boxes) == 2 for row in analysis.rows], dtype=bool)


def gaps(analysis: Analysis) -> np.ndarray:
    """Inter-fighter gaps, with `nan` where both fighters were not visible."""
    return np.array(
        [row.gap if row.gap is not None else np.nan for row in analysis.rows], dtype=float
    )


def sharpness(analysis: Analysis) -> np.ndarray:
    return np.array([row.sharpness for row in analysis.rows], dtype=float)


def window_mask(analysis: Analysis, start: float, end: float) -> np.ndarray:
    stamps = times(analysis)
    return (stamps >= start) & (stamps <= end)
