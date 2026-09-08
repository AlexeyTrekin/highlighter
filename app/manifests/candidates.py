"""`candidates.json` — windows with their scores, verdicts and drop reasons."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.manifests.base import Manifest

Kind = Literal["short", "long"]
Verdict = Literal["keep", "drop", "unsure"]
Side = Literal["L", "R"]

# What a clip contains, which decides where in the music it may go (`spec/006_music.md`).
# "unknown" is a real verdict, not a placeholder: fencing is a continuum and a window near the
# thresholds is genuinely undecided. Forcing it either way is how a fight clip lands under a
# quiet chord with a green check.
Material = Literal["action", "non_action", "unknown"]

# How a window came to be proposed. The gates differ: an exchange needs both fighters in
# frame to be worth anything, while a walk-on with one person is exactly intro material.
Origin = Literal["halt", "fallback", "calm"]

# A clip is normally at least two bars — one action. The reel's opening may be a single bar,
# so a section whose first musical step falls one bar in can still be cut there instead of at
# an arbitrary later bar (`spec/006_music.md`). This is the floor for any slot, and therefore
# the floor the candidate gate uses.
MIN_BARS: int = 2
OPENING_MIN_BARS: int = 1


class Features(BaseModel):
    model_config = ConfigDict(extra="forbid")

    peak_activity: float = 0.0
    median_sharpness: float = 0.0
    both_visible_frac: float = 0.0
    min_gap: float | None = None
    closing_speed: float | None = None
    # How much the distance between the fighters moves over the window, in body-heights.
    # Fencing swings it; an embrace or a walk-on holds it steady however vigorous they look.
    gap_variation: float | None = None
    # How often they cross from out of measure to in, or back. An exchange does this; two
    # people standing at salute, or hugging, do not.
    measure_crossings: int = 0


class AgentVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    reason: str
    confidence: float | None = None


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_id: str
    start: float
    end: float
    anchor: float
    kind: Kind
    origin: Origin = "halt"
    material: Material = "unknown"
    features: Features = Field(default_factory=Features)
    score: float = 0.0
    agent: AgentVerdict | None = None
    target_side: Side | None = None
    flags: list[str] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


class Candidates(Manifest):
    stage: str = "candidates"
    candidates: list[Candidate] = Field(default_factory=list)


def usable(candidate: Candidate) -> bool:
    """Whether the candidate survived its quality gates.

    Nothing is deleted from the manifest — a dropped window keeps its reason so a decision can
    be audited or reversed (`spec/002_manifests.md`).
    """
    return not candidate.flags


def max_bars(candidate: Candidate, bar_s: float, source_duration: float) -> int:
    """Longest whole-bar slot this candidate's source can actually fill.

    Anchored at the window end, a clip reaches back `bars * bar_s`. Asking for more than the
    source holds is what produced frozen tails in the prototype, so the arithmetic that
    decides slot length lives here, next to the candidate that constrains it.
    """
    available = min(candidate.end, source_duration)
    return int(available / bar_s)


def fits_minimum(candidate: Candidate, bar_s: float, source_duration: float) -> bool:
    """Whether the source can fill the shortest slot the director may create."""
    return max_bars(candidate, bar_s, source_duration) >= OPENING_MIN_BARS
