"""Command-line entry point: subcommands over an intake folder.

    lawnlord start [root]    scaffold an intake folder

The intake standard is the deterministic zip (schema.json + data.json + files/
+ pages/) produced by ``jwogrady/rake``. The zip -> DuckDB build and the case
viewer are rebuilt on the following branches; this layer currently scaffolds the
intake location and resolves a configurable intake root.

``root`` defaults to the current directory; lawnlord resolves the intake/corpus
locations from it (honoring an optional lawnlord.toml).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .console import console
from .intake import load_intake, scaffold


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Project root containing the intake (default: current directory)",
    )


def _intake_root() -> Path:
    """Where intake folders live. Configurable so the case data can sit in a
    **separate repo** or **local in the project**:

    1. ``LAWNLORD_INTAKE`` env var (highest precedence),
    2. ``lawnlord.toml`` ``[lawnlord] intake`` at the cwd (absolute or relative),
    3. ``./intake`` (the in-project default).
    """
    env = os.environ.get("LAWNLORD_INTAKE")
    if env:
        return Path(env).expanduser().resolve()
    return load_intake(".").intake_dir


def _resolve_intake(arg: str) -> Path:
    """Resolve an intake folder from a command argument: an explicit path
    (used as-is) **or** a bare name resolved under the configured intake root."""
    p = Path(arg)
    if p.is_dir():
        return p.resolve()
    return (_intake_root() / arg).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lawnlord",
        description="Build a queryable case index from the deterministic intake zip.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="Scaffold an intake folder")
    _add_root(p_start)
    p_start.add_argument(
        "--force", action="store_true", help="Overwrite an existing config / intake README"
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    """Entry point. Report known input errors cleanly (a clear message and exit
    1, no traceback); let unexpected errors surface for debugging."""
    try:
        _main(argv)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise SystemExit(1) from None


def _main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "start":
        touched = scaffold(args.root, force=args.force)
        intake = load_intake(args.root)
        if touched:
            console.print("[bold]Scaffolded intake:[/]")
            for path in touched:
                console.print(f"  + {path}")
        else:
            console.print("[yellow]Intake already scaffolded; nothing to create.[/]")
        console.print(
            f"Drop the intake zip in [bold]{intake.intake_dir}[/]."
        )
        return
