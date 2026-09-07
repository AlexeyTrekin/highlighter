import subprocess

import pytest

from app import host


def test_check_python_passes_on_supported_interpreter():
    check = host.check_python()

    assert check.ok
    assert check.name == "python"


def test_run_checks_covers_every_prerequisite():
    names = [c.name for c in host.run_checks()]

    assert names == ["python", "ffmpeg", "ffprobe"]


@pytest.mark.parametrize(
    ("check", "binary"),
    [(host.check_ffmpeg, "ffmpeg"), (host.check_ffprobe, "ffprobe")],
)
def test_missing_binary_is_reported_with_an_actionable_detail(monkeypatch, check, binary):
    monkeypatch.setattr(host.shutil, "which", lambda _: None)

    result = check()

    assert result.name == binary
    assert not result.ok
    assert "install ffmpeg" in result.detail


def test_ffmpeg_without_libvidstab_fails_the_check(monkeypatch):
    monkeypatch.setattr(host.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(host, "has_stabilize_filter", lambda _ffmpeg: False)

    result = host.check_ffmpeg()

    assert not result.ok
    assert host.STABILIZE_FILTER in result.detail


def test_stabilize_filter_probe_survives_a_missing_binary(monkeypatch):
    def explode(*_args, **_kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(subprocess, "run", explode)

    assert host.has_stabilize_filter() is False


def test_stabilize_filter_probe_reads_the_filter_list(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=" T.. vidstabtransform  V->V  Transform\n", stderr=""
        ),
    )

    assert host.has_stabilize_filter() is True


def test_stabilize_filter_probe_uses_the_binary_it_was_given(monkeypatch):
    """The check must describe the same ffmpeg `check_ffmpeg` resolved, not whatever PATH holds."""
    invoked: list[list[str]] = []

    def record(cmd, **_kwargs):
        invoked.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", record)
    monkeypatch.setattr(host.shutil, "which", lambda _: "/opt/custom/bin/ffmpeg")

    host.check_ffmpeg()

    assert invoked[0][0] == "/opt/custom/bin/ffmpeg"
