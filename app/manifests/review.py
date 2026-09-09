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


Mode = Literal["auto", "strict", "weighted"]

# The ends of the weight axis. A weight says where along the reel a clip goes, low first
# (`spec/007_review_ui.md`); it is not a score and has nothing to do with the scoring weights in
# `project.json`.
WEIGHT_MIN: float = 0.0
WEIGHT_MAX: float = 100.0


class Order(BaseModel):
    """How the user wants the reel ordered (`spec/002_manifests.md`).

    Order only — never a bar or a second. Which bars a clip occupies follows from the slot plan
    and the music grid, so a user-facing position that meant a bar index would silently point at
    a different clip whenever the music analysis changed.
    """

    model_config = ConfigDict(extra="forbid")

    mode: Mode = "auto"
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


def effective_weights(order: Order) -> dict[str, float]:
    """Position weights with the opening and ending buckets folded in.

    The buckets are shorthand for the two ends of the axis, so the page can offer "send to the
    start" next to the slider without a second concept underneath it. An explicit weight wins
    over a bucket, being the more specific statement of the same thing.
    """
    return {
        **dict.fromkeys(order.opening, WEIGHT_MIN),
        **dict.fromkeys(order.ending, WEIGHT_MAX),
        **order.weights,
    }


def pins(order: Order) -> list[str]:
    """Every candidate the user gave a position, in whichever way the mode uses."""
    if order.mode == "strict":
        return list(dict.fromkeys(order.sequence))
    if order.mode == "weighted":
        return list(effective_weights(order))
    return []


def touched(review: Review) -> int:
    """How many candidates the human actually ruled on.

    Reported back so the agent can say whether the edit was reviewed or chosen for the user
    (`spec/009_agent_surface.md`) rather than leaving them to guess.
    """
    return sum(1 for verdict in review.verdicts.values() if verdict != DEFAULT_VERDICT)
