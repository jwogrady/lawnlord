"""Command-line entry point: subcommands over an intake folder.

    lawnlord start [root]     scaffold an intake folder
    lawnlord import <zip>     import a rake intake zip into a per-case DuckDB

The intake standard is the deterministic zip (schema.json + data.json + files/
+ pages/) produced by ``jwogrady/rake``. ``import`` extracts it safely, validates
``data.json`` against the bundled ``schema.json``, and builds the DuckDB mirror.

``root`` defaults to the current directory; lawnlord resolves the intake/corpus
locations from it (honoring an optional lawnlord.toml).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from rich.table import Table

from .console import console
from .db import apply_schema, open_case_db
from .export import export_actual
from .ingest import ingest_case
from .intake import load_intake, scaffold
from .reader import captured_at, extract_zip
from .workspace import Case


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

    p_import = sub.add_parser(
        "import",
        help="Import a rake intake zip (or its extracted dir) into a per-case DuckDB",
    )
    p_import.add_argument("source", help="Path to the intake zip, or an extracted intake dir")
    p_import.add_argument(
        "--case-dir", default=None, help="Output root for lawnlord.duckdb (default: cwd)"
    )

    p_export = sub.add_parser(
        "export-actual",
        help="Print the Actual-lens view (case + parties + register of actions) as JSON",
    )
    p_export.add_argument(
        "--case-dir", default=".", help="Case root holding lawnlord.duckdb (default: cwd)"
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

    if args.command == "import":
        case_dir = Path(args.case_dir).resolve() if args.case_dir else Path.cwd()
        source = Path(args.source)
        # A directory is treated as already-extracted intake; a zip is extracted
        # (safely) under <case-dir>/intake/<stem> first.
        if source.is_dir():
            intake_dir = source.resolve()
        else:
            intake_dir = case_dir / "intake" / source.stem
            extract_zip(source, intake_dir)
        case = Case.from_intake(intake_dir, case_dir=case_dir)
        con = open_case_db(case.duckdb_path)
        apply_schema(con)
        stats = ingest_case(con, case, captured_at(intake_dir))
        con.close()
        table = Table(title="Imported case (zip → DuckDB mirror)")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Case", case.case_number)
        table.add_row("Parties", str(stats["parties"]))
        table.add_row("Events", str(stats["events"]))
        table.add_row("Images (filed PDFs)", str(stats["images"]))
        table.add_row("Image↔event links", str(stats["image_events"]))
        table.add_row("DuckDB", str(case.duckdb_path))
        console.print(table)
        if stats["skipped_images"]:
            console.print(
                f"[yellow]Skipped (no source PDF):[/] {len(stats['skipped_images'])}"
            )
        console.print("[green]Done.[/]")
        return

    if args.command == "export-actual":
        # Emit ONLY JSON on stdout so the viewer can parse it; the data comes
        # from the DuckDB mirror, read-only.
        import json

        con = open_case_db(Path(args.case_dir) / "lawnlord.duckdb", read_only=True)
        try:
            print(json.dumps(export_actual(con)))
        finally:
            con.close()
        return
