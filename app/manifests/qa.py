"""`render/qa.json` — automated checks that run before a reel is presented."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.manifests.base import Manifest

Status = Literal["pass", "warn", "fail"]

# Worst-first, so a set of statuses collapses to the most severe one.
_SEVERITY: dict[Status, int] = {"pass": 0, "warn": 1, "fail": 2}


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    target: str
    status: Status
    detail: str


class Qa(Manifest):
    stage: str = "render"
    status: Status = "pass"
    checks: list[Check] = Field(default_factory=list)


def overall(checks: list[Check]) -> Status:
    return max((c.status for c in checks), key=lambda s: _SEVERITY[s], default="pass")


def build(checks: list[Check]) -> Qa:
    return Qa(status=overall(checks), checks=checks)


def failures(report: Qa) -> list[Check]:
    return [c for c in report.checks if c.status == "fail"]


def warnings(report: Qa) -> list[Check]:
    return [c for c in report.checks if c.status == "warn"]
