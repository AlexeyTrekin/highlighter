import json

import pytest
from typer.testing import CliRunner

from app import __version__, host
from app.cli import EXIT_PREREQUISITE, cli

runner = CliRunner()


def test_version_command_reports_the_package_version():
    result = runner.invoke(cli, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_version_command_has_a_machine_readable_form():
    result = runner.invoke(cli, ["version", "--json"])

    assert json.loads(result.stdout) == {"version": __version__}


def test_doctor_reports_every_prerequisite():
    result = runner.invoke(cli, ["doctor", "--json"])

    payload = json.loads(result.stdout)
    assert {c["name"] for c in payload["checks"]} == {"python", "ffmpeg", "ffprobe"}


@pytest.mark.parametrize(
    ("ffmpeg_ok", "expected_exit"),
    [(True, 0), (False, EXIT_PREREQUISITE)],
)
def test_doctor_exit_code_distinguishes_a_missing_prerequisite(
    monkeypatch, ffmpeg_ok, expected_exit
):
    """Exit 3 is part of the CLI contract (spec/009_agent_surface.md), so pin both branches.

    The host's real ffmpeg state would otherwise decide which branch runs, and on a machine
    that can actually render the failing path would never execute.
    """
    checks = [
        host.Check("python", True, "3.12"),
        host.Check("ffmpeg", ffmpeg_ok, "stubbed"),
        host.Check("ffprobe", True, "stubbed"),
    ]
    monkeypatch.setattr(host, "run_checks", lambda: checks)

    result = runner.invoke(cli, ["doctor", "--json"])

    assert result.exit_code == expected_exit
    assert json.loads(result.stdout)["ok"] is ffmpeg_ok


def test_doctor_human_output_marks_the_failing_check(monkeypatch):
    monkeypatch.setattr(
        host,
        "run_checks",
        lambda: [host.Check("ffmpeg", False, "not found — install ffmpeg")],
    )

    result = runner.invoke(cli, ["doctor"])

    assert "FAIL" in result.stdout
    assert "install ffmpeg" in result.stdout


@pytest.mark.needs_ffmpeg
def test_doctor_probes_the_real_ffmpeg_when_the_host_has_one():
    """Exercises the live subprocess probe, and the `needs_ffmpeg` skip path itself.

    Asserts the binary was resolved rather than that it carries libvidstab: a host whose
    ffmpeg lacks the filter is a host that cannot render, which is `doctor`'s job to report
    and not a test failure.
    """
    result = runner.invoke(cli, ["doctor", "--json"])

    checks = {c["name"]: c for c in json.loads(result.stdout)["checks"]}
    assert "not found" not in checks["ffmpeg"]["detail"]
