"""`hlreel` command line — the project's contract with any agent (`spec/009_agent_surface.md`).

Commands are non-interactive and report machine-readable results, so an agent never has to
parse prose. Exit codes: 0 success, 1 stage failure, 2 bad input, 3 missing prerequisite.
"""

import json

import typer

from app import __version__, host

EXIT_PREREQUISITE = 3

cli = typer.Typer(
    add_completion=False, help="Build a music-cut highlight reel from tournament footage."
)


@cli.command()
def doctor(as_json: bool = typer.Option(False, "--json", help="Emit the results as JSON.")) -> None:
    """Check host prerequisites."""
    checks = host.run_checks()
    if as_json:
        payload = [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks]
        typer.echo(json.dumps({"ok": all(c.ok for c in checks), "checks": payload}, indent=2))
    else:
        for check in checks:
            typer.echo(f"{'ok  ' if check.ok else 'FAIL'}  {check.name:8s} {check.detail}")
    if not all(c.ok for c in checks):
        raise typer.Exit(EXIT_PREREQUISITE)


@cli.command()
def version(as_json: bool = typer.Option(False, "--json", help="Emit the result as JSON.")) -> None:
    """Print the package version."""
    typer.echo(json.dumps({"version": __version__}) if as_json else __version__)


def main() -> None:
    cli()
