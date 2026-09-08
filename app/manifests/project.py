"""`project.json` — project identity, options and per-stage status."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.manifests.base import Manifest

Mode = Literal["event", "personal"]
Shape = Literal["short", "long"]
StageState = Literal["pending", "running", "done", "failed"]

# A source at or below this length holds a single exchange ending near its end; longer ones
# need the peak-finding path (`spec/003_pipeline.md`).
SHORT_MAX_S: float = 9.0


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    original_name: str
    path: str
    duration_s: float
    fps: float
    width: int
    height: int
    shape: Shape
    # A coarse greyscale thumbnail of a mid-file frame, flattened. Clips arriving through a
    # messenger are routinely uploaded twice under different names, and identical footage in
    # two slots is the kind of thing a viewer notices immediately and a checksum never would,
    # since re-encoding changes every byte.
    signature: list[int] = Field(default_factory=list)


class ScoringWeights(BaseModel):
    """How the composite score trades its features off against each other.

    Configuration rather than code constants because these are exactly what the benchmark
    tunes against recorded human verdicts (`spec/005_scoring.md`). The `*_scale` values are
    the level at which a raw feature counts as full marks.
    """

    model_config = ConfigDict(extra="forbid")

    peak_activity: float = 1.0
    closing_speed: float = 1.0
    both_visible_frac: float = 0.5
    min_gap: float = 0.5
    median_sharpness: float = 0.25

    activity_scale: float = 20.0
    closing_scale: float = 2.0
    sharpness_scale: float = 500.0

    def for_feature(self, name: str) -> float:
        return float(getattr(self, name))


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_s: float = 60.0
    width: int = 1920
    height: int = 1080
    fps: int = 30
    max_candidates: int = 50
    weights: ScoringWeights = Field(default_factory=ScoringWeights)


class StageStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StageState = "pending"
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


class Project(Manifest):
    stage: str = "ingest"
    id: str
    created_at: str
    mode: Mode = "event"
    target_hint: str | None = None
    options: Options = Field(default_factory=Options)
    music_path: str | None = None
    sources: list[Source] = Field(default_factory=list)
    stages: dict[str, StageStatus] = Field(default_factory=dict)


def classify_shape(duration_s: float) -> Shape:
    return "short" if duration_s <= SHORT_MAX_S else "long"


def source_by_id(project: Project, source_id: str) -> Source:
    for source in project.sources:
        if source.id == source_id:
            return source
    raise KeyError(f"no source {source_id!r} in project {project.id!r}")
