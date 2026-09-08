"""`--force` invalidates nothing downstream, so the CLI has to say what went stale.

Without the warning, re-cutting the EDL leaves `render` marked done and the next run reports
"nothing to do" while the reel still shows the previous edit (`spec/003_pipeline.md`).
"""

from pathlib import Path

import pytest
import typer

from app import cli
from app.manifests.project import Project, StageStatus


def project_with(done: list[str]) -> Project:
    return Project(
        id="p",
        created_at="2026-09-08T00:00:00+00:00",
        stages={name: StageStatus(status="done") for name in done},
    )


def warnings(monkeypatch, project: Project, executed: list[str]) -> list[str]:
    lines: list[str] = []
    monkeypatch.setattr(typer, "echo", lambda msg, **_: lines.append(str(msg)))
    cli._warn_stale(Path("/tmp/p"), project, executed)
    return lines


def test_a_re_cut_edl_marks_the_existing_render_stale(monkeypatch):
    project = project_with(["music", "candidates", "director", "render"])

    lines = warnings(monkeypatch, project, executed=["director"])

    assert len(lines) == 1
    assert "render" in lines[0]


def test_a_full_run_warns_about_nothing(monkeypatch):
    """Every stage ran in order, so each is built on the one before it."""
    project = project_with(["music", "candidates", "director", "render"])

    assert warnings(monkeypatch, project, ["music", "candidates", "director", "render"]) == []


def test_the_last_stage_has_no_downstream(monkeypatch):
    project = project_with(["music", "candidates", "director", "render"])

    assert warnings(monkeypatch, project, ["render"]) == []


@pytest.mark.parametrize("executed", [[], ["music"]])
def test_nothing_is_stale_when_downstream_never_ran(monkeypatch, executed):
    project = project_with(["music"])

    assert warnings(monkeypatch, project, executed) == []
