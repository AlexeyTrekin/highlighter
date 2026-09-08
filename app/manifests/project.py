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


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_s: float = 60.0
    width: int = 1920
    height: int = 1080
    fps: int = 30
    max_candidates: int = 50


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
