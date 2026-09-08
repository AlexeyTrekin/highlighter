import subprocess

import pytest

from app import assets, host


def test_check_python_passes_on_supported_interpreter():
    check = host.check_python()

    assert check.ok
    assert check.name == "python"


def test_run_checks_covers_the_host_tools_and_every_model():
    names = [c.name for c in host.run_checks()]

    assert names[:3] == ["python", "ffmpeg", "ffprobe"]
    assert set(assets.REGISTRY) <= set(names), "a model nothing checks for fails mid-analysis"


def test_a_missing_model_is_reported_with_the_command_that_fixes_it(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(
        assets.Asset, "path", property(lambda self: tmp_path / self.name), raising=False
    )

    checks = {c.name: c for c in host.check_models()}

    missing = checks[assets.YOLOV8N.name]
    assert not missing.ok
    assert "fetch-models" in missing.hint


@pytest.mark.parametrize(
    ("check", "binary"),
    [(host.check_ffmpeg, "ffmpeg"), (host.check_ffprobe, "ffprobe")],
)
def test_missing_binary_is_reported_with_an_actionable_hint(monkeypatch, check, binary):
    """The hint must name `ffmpeg-full`: the plain Homebrew formula omits libvidstab."""
    monkeypatch.setattr(host.shutil, "which", lambda _: None)

    result = check()

    assert result.name == binary
    assert not result.ok
    assert "ffmpeg-full" in result.hint


def test_ffmpeg_without_libvidstab_fails_the_check(monkeypatch):
    monkeypatch.setattr(host.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(host, "has_stabilize_filter", lambda _ffmpeg: False)

    result = host.check_ffmpeg()

    assert not result.ok
    assert host.STABILIZE_FILTER in result.detail
    assert "ffmpeg-full" in result.hint


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
