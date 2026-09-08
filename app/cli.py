"""`hlreel` command line — the project's contract with any agent (`spec/009_agent_surface.md`).

Commands are non-interactive and report machine-readable results, so an agent never has to
parse prose. Exit codes: 0 success, 1 stage failure, 2 bad input, 3 missing prerequisite.
"""

import contextlib
import json
from pathlib import Path

import typer

from app import __version__, assets, host, pipeline
from app import project as project_store
from app.manifests import base, qa
from app.manifests.edl import Edl
from app.manifests.project import Options, Project
from app.manifests.qa import Qa
from app.stages import ingest as ingest_stage
from app.stages import music as music_stage

EXIT_STAGE_FAILED = 1
EXIT_BAD_INPUT = 2
EXIT_PREREQUISITE = 3

cli = typer.Typer(
    add_completion=False, help="Build a music-cut highlight reel from tournament footage."
)


@cli.command()
def doctor(as_json: bool = typer.Option(False, "--json", help="Emit the results as JSON.")) -> None:
    """Check host prerequisites."""
    checks = host.run_checks()
    failed = [c for c in checks if not c.ok]
    if as_json:
        payload = [{"name": c.name, "ok": c.ok, "detail": c.detail, "hint": c.hint} for c in checks]
        typer.echo(json.dumps({"ok": not failed, "checks": payload}, indent=2))
    else:
        for check in checks:
            typer.echo(f"{'ok  ' if check.ok else 'FAIL'}  {check.name:8s} {check.detail}")
        for hint in dict.fromkeys(c.hint for c in failed if c.hint):
            typer.echo(f"\n{hint}")
    if failed:
        raise typer.Exit(EXIT_PREREQUISITE)


@cli.command()
def version(as_json: bool = typer.Option(False, "--json", help="Emit the result as JSON.")) -> None:
    """Print the package version."""
    typer.echo(json.dumps({"version": __version__}) if as_json else __version__)


@cli.command(name="fetch-models")
def fetch_models(
    force: bool = typer.Option(False, "--force", help="Re-download even if a copy is present."),
) -> None:
    """Download the model files the pipeline needs.

    Weights are not in the repository — they are large and not ours to redistribute — so this
    is the one command that reaches the network.
    """
    for asset in assets.REGISTRY.values():
        typer.echo(f"{asset.name}: {asset.purpose}")
        typer.echo(f"  from {asset.url}")
        try:
            path = assets.fetch(asset, force=force)
        except assets.AssetError as error:
            typer.echo(f"  failed: {error}", err=True)
            raise typer.Exit(EXIT_STAGE_FAILED) from error
        typer.echo(f"  -> {path} ({path.stat().st_size / 1e6:.1f} MB)")


@cli.command()
def init(
    directory: Path = typer.Argument(..., help="Project directory to create."),
    mode: str = typer.Option("event", "--mode", help="event or personal."),
    music: Path | None = typer.Option(None, "--music", help="Music track."),
    target: str | None = typer.Option(None, "--target", help="Target fighter description."),
    duration: float = typer.Option(60.0, "--duration", help="Target reel length in seconds."),
) -> None:
    """Create a project."""
    if mode not in ("event", "personal"):
        typer.echo(f"unknown mode {mode!r}; use 'event' or 'personal'", err=True)
        raise typer.Exit(EXIT_BAD_INPUT)
    if music is not None and not music.is_file():
        typer.echo(f"no music track at {music}", err=True)
        raise typer.Exit(EXIT_BAD_INPUT)

    project = Project(
        id=directory.name,
        created_at=project_store.now(),
        mode=mode,  # type: ignore[arg-type]
        target_hint=target,
        music_path=str(music.resolve()) if music else None,
        options=Options(duration_s=duration),
    )
    try:
        project_store.create(directory, project)
    except FileExistsError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(EXIT_BAD_INPUT) from error
    typer.echo(f"created {directory}")


@cli.command()
def add(
    directory: Path = typer.Argument(..., help="Project directory."),
    paths: list[Path] = typer.Argument(..., help="Video files or directories to ingest."),
) -> None:
    """Register footage with the project."""
    project = _load(directory)
    missing = [p for p in paths if not p.exists()]
    if missing:
        typer.echo(f"no such path: {missing[0]}", err=True)
        raise typer.Exit(EXIT_BAD_INPUT)

    before = len(project.sources)
    with _locked(directory):
        project = ingest_stage.run(project, paths)
        project_store.mark_done(directory, project, ingest_stage.STAGE)
    typer.echo(f"{len(project.sources) - before} added, {len(project.sources)} sources total")


@cli.command()
def run(
    directory: Path = typer.Argument(..., help="Project directory."),
    stage: str | None = typer.Option(None, "--stage", help="Run one stage instead of all."),
    force: bool = typer.Option(False, "--force", help="Re-run stages already marked done."),
) -> None:
    """Run the pipeline."""
    project = _load(directory)
    stages = pipeline.ORDER if stage is None else (stage,)
    unknown = [s for s in stages if s not in pipeline.RUNNERS]
    if unknown:
        typer.echo(f"unknown stage {unknown[0]!r}; pick from {', '.join(pipeline.ORDER)}", err=True)
        raise typer.Exit(EXIT_BAD_INPUT)

    with _locked(directory):
        try:
            executed = pipeline.run(directory, project, stages, force)
        except pipeline.StageBlocked as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(EXIT_PREREQUISITE) from error
        except Exception as error:
            typer.echo(f"stage failed: {error}", err=True)
            raise typer.Exit(EXIT_STAGE_FAILED) from error

    typer.echo(f"ran: {', '.join(executed) or 'nothing (already done; use --force)'}")
    _warn_stale(directory, project, executed)

    if "render" in executed:
        report = base.read(project_store.qa_path(directory), Qa)
        _report_qa(report, directory)
        if qa.failures(report):
            raise typer.Exit(EXIT_STAGE_FAILED)


@cli.command()
def status(
    directory: Path = typer.Argument(..., help="Project directory."),
    as_json: bool = typer.Option(False, "--json", help="Emit the status as JSON."),
) -> None:
    """Report project and stage state."""
    project = _load(directory)
    stages = {name: project_store.stage_status(project, name).status for name in pipeline.ORDER}
    payload = {
        "id": project.id,
        "mode": project.mode,
        "sources": len(project.sources),
        "music": project.music_path,
        "stages": {"ingest": project_store.stage_status(project, "ingest").status, **stages},
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(f"{payload['id']}  mode={payload['mode']}  sources={payload['sources']}")
    for name, state in payload["stages"].items():
        typer.echo(f"  {name:11s} {state}")


@cli.command()
def edl(
    directory: Path = typer.Argument(..., help="Project directory."),
    show: bool = typer.Option(False, "--show", help="Print the current EDL."),
    set_from: Path | None = typer.Option(None, "--set", help="Replace the EDL from a file."),
) -> None:
    """Inspect or replace the edit decision list."""
    _load(directory)
    if set_from is not None:
        if not set_from.is_file():
            typer.echo(f"no EDL at {set_from}", err=True)
            raise typer.Exit(EXIT_BAD_INPUT)
        replacement = base.read(set_from, Edl)
        with _locked(directory):
            base.write(project_store.edl_path(directory), replacement)
        typer.echo(f"EDL replaced: {len(replacement.clips)} clips")
        typer.echo("render is now stale; re-run `hlreel render --force`", err=True)
        return

    current = pipeline.load_edl(directory)
    if show:
        typer.echo(base.dumps(current))
        return
    for clip in current.clips:
        typer.echo(
            f"bar {clip.grid_slot:>3} +{clip.bars}  {clip.source_id}  "
            f"{clip.in_:6.2f}-{clip.out:6.2f}  {clip.section:8s}  {clip.order_reason}"
        )


@cli.command()
def render(
    directory: Path = typer.Argument(..., help="Project directory."),
    force: bool = typer.Option(False, "--force", help="Re-render clips that already exist."),
) -> None:
    """Render the reel from the current EDL and report QA."""
    project = _load(directory)
    with _locked(directory):
        if force:
            for stale in project_store.render_dir(directory).glob("c[0-9][0-9][0-9]_*.mp4"):
                stale.unlink()
        project_store.mark_running(directory, project, "render")
        try:
            report = pipeline.run_render(directory, project)
        except Exception as error:
            project_store.mark_failed(directory, project, "render", str(error))
            typer.echo(f"render failed: {error}", err=True)
            raise typer.Exit(EXIT_STAGE_FAILED) from error
        project_store.mark_done(directory, project, "render")

    _report_qa(report, directory)
    if qa.failures(report):
        raise typer.Exit(EXIT_STAGE_FAILED)


@cli.command()
def music(
    directory: Path = typer.Argument(..., help="Project directory."),
    as_json: bool = typer.Option(False, "--json", help="Emit the grid as JSON."),
) -> None:
    """Report the fitted music grid and how well it matches the track."""
    _load(directory)
    analysis = pipeline.load_music(directory)
    ok, detail = music_stage.validate_grid(analysis)
    payload = {
        "bpm": analysis.grid.bpm,
        "bar_s": analysis.grid.bar_s,
        "first_downbeat_s": analysis.grid.first_downbeat_s,
        "bars": len(analysis.bars),
        "sections": [
            {"name": s.name, "level": s.level, "bars": [s.bar_start, s.bar_end]}
            for s in analysis.sections
        ],
        "grid_check": {"ok": ok, "detail": detail},
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(
        f"{analysis.grid.bpm:.2f} BPM  bar {analysis.grid.bar_s:.4f}s  "
        f"downbeat {analysis.grid.first_downbeat_s:.3f}s  {len(analysis.bars)} bars"
    )
    typer.echo(f"{'ok' if ok else 'SUSPECT'}: {detail}")
    for section in analysis.sections:
        typer.echo(
            f"  {section.level:5s} {section.name:8s} bars {section.bar_start}-{section.bar_end}"
        )


@contextlib.contextmanager
def _locked(directory: Path):
    """Hold the project lock, turning a conflict into a documented exit code.

    Every command that writes a manifest takes it: two writers on one project directory
    produce a directory whose parts disagree.
    """
    try:
        project_store.acquire_lock(directory)
    except RuntimeError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(EXIT_STAGE_FAILED) from error
    try:
        yield
    finally:
        project_store.release_lock(directory)


def _warn_stale(directory: Path, project: Project, executed: list[str]) -> None:
    """Say when a completed stage now rests on something that changed underneath it.

    `--force` re-runs one stage and invalidates nothing downstream (`spec/003_pipeline.md`),
    so without this a re-cut EDL leaves `render` marked done and the next run reports
    "nothing to do" while the reel still shows the previous edit.
    """
    for stage in executed:
        downstream = pipeline.ORDER[pipeline.ORDER.index(stage) + 1 :]
        # Only stages that were already done and did **not** re-run in this invocation: a
        # stage that ran after `stage` in the same pass is built on the new output, not stale.
        stale = [s for s in downstream if s not in executed and project_store.is_done(project, s)]
        if stale:
            typer.echo(
                f"warning: {', '.join(stale)} predates this {stage} run and is now stale; "
                f"re-run with --force",
                err=True,
            )
            return


def _report_qa(report: Qa, directory: Path) -> None:
    for check in report.checks:
        typer.echo(f"{check.status.upper():5s} {check.name:18s} {check.target}: {check.detail}")
    reel = project_store.latest_reel(directory)
    if reel is not None:
        typer.echo(f"\n{reel}")


def _load(directory: Path) -> Project:
    try:
        return project_store.load(directory)
    except FileNotFoundError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(EXIT_BAD_INPUT) from error


def main() -> None:
    cli()
