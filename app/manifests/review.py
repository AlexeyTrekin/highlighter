"""`review.json` — what the human decided.

Everything here is an override. A project nobody opened has an empty `review.json`, or none at
all, and the director still produces a reel (`spec/007_review_ui.md`).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.manifests.base import Manifest

# The user's own vocabulary: irrelevant / average / best.
Verdict = Literal["drop", "agent", "keep"]
DEFAULT_VERDICT: Verdict = "agent"


class Trim(BaseModel):
    """A window the user adjusted by hand."""

    model_config = ConfigDict(extra="forbid")

    start: float
    end: float


class Order(BaseModel):
    """Ordering hints (`spec/002_manifests.md`).

    Carried but not yet acted on: the drag-to-sequence UI and the director side that makes a
    pinned position binding arrive with WAL 3.2. Present now because the field is part of the
    documented manifest, and a `review.json` that names it must not make the project
    unopenable. `hlreel run` says when hints are set and ignored, so no pin fails silently.
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto", "strict", "weighted"] = "auto"
    sequence: list[str] = Field(default_factory=list)
    opening: list[str] = Field(default_factory=list)
    ending: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)


class Review(Manifest):
    stage: str = "review"
    verdicts: dict[str, Verdict] = Field(default_factory=dict)
    trims: dict[str, Trim] = Field(default_factory=dict)
    notes: dict[str, str] = Field(default_factory=dict)
    order: Order = Field(default_factory=Order)
    completed: bool = False
    updated_at: str | None = None


def verdict_for(review: Review, candidate_id: str) -> Verdict:
    """What the human said about this candidate, or that they left it to the agent.

    An absent entry is `agent`, which is what makes the review step genuinely optional
    (`spec/002_manifests.md`).
    """
    return review.verdicts.get(candidate_id, DEFAULT_VERDICT)


def is_dropped(review: Review, candidate_id: str) -> bool:
    return verdict_for(review, candidate_id) == "drop"


def is_kept(review: Review, candidate_id: str) -> bool:
    return verdict_for(review, candidate_id) == "keep"


def trim_for(review: Review, candidate_id: str) -> Trim | None:
    return review.trims.get(candidate_id)


def ordering_hints(review: Review) -> list[str]:
    """Which parts of `review.json.order` ask for something, in the user's words.

    Empty for the default `auto` with nothing pinned, which is what an untouched project has.
    """
    named = [
        f"{len(getattr(review.order, field))} {field}"
        for field in ("sequence", "opening", "ending", "weights")
        if getattr(review.order, field)
    ]
    if review.order.mode != "auto":
        named.insert(0, f"mode {review.order.mode}")
    return named


def touched(review: Review) -> int:
    """How many candidates the human actually ruled on.

    Reported back so the agent can say whether the edit was reviewed or chosen for the user
    (`spec/009_agent_surface.md`) rather than leaving them to guess.
    """
    return sum(1 for verdict in review.verdicts.values() if verdict != DEFAULT_VERDICT)
