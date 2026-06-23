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
import shutil
from pathlib import Path

from rich.table import Table

from .console import console
from .db import apply_schema, open_case_db
from .explode import explode_case
from .export import export_actual, export_exploded
from .ingest import ingest_case
from .intake import load_intake, scaffold
from .reader import captured_at, extract_zip, find_intake_dir
from .transcribe import (
    DEFAULT_LOCAL_MODEL,
    DEFAULT_MODEL,
    DEFAULT_WORKERS,
    CloudTranscriber,
    LocalTranscriber,
    escalate_case,
    installed_vision_models,
    make_client,
    measure_case,
    ollama_available,
    transcribe_case,
)
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

    p_export_x = sub.add_parser(
        "export-exploded",
        help="Print the Exploded-lens view (images → documents → pages + transcription) as JSON",
    )
    p_export_x.add_argument(
        "--case-dir", default=".", help="Case root holding lawnlord.duckdb (default: cwd)"
    )

    p_explode = sub.add_parser(
        "explode",
        help="Explode filed PDFs into documents + page PNGs (the Exploded layer)",
    )
    p_explode.add_argument(
        "--case-dir", default=".", help="Case root holding lawnlord.duckdb (default: cwd)"
    )
    p_explode.add_argument(
        "--dpi", type=int, default=150, help="Render DPI for the page PNGs (default: 150)"
    )

    p_transcribe = sub.add_parser(
        "transcribe",
        help="Transcribe each page PNG with Claude vision (cloud opt-in; needs ANTHROPIC_API_KEY)",
    )
    p_transcribe.add_argument(
        "--case-dir", default=".", help="Case root holding lawnlord.duckdb (default: cwd)"
    )
    p_transcribe.add_argument(
        "--backend", choices=("all", "cloud", "local"), default="all",
        help="Which vision tier(s) read each page: 'all' (the default — cloud "
        "Claude when ANTHROPIC_API_KEY is set, plus every installed Ollama vision "
        "model; ADR-0006), 'cloud' (only Claude), or 'local' (only Ollama).",
    )
    p_transcribe.add_argument(
        "--model", default=None,
        help=f"Override the vision model (cloud default: {DEFAULT_MODEL}; "
        f"local default: {DEFAULT_LOCAL_MODEL})",
    )
    p_transcribe.add_argument(
        "--ollama-host", default=None,
        help="Ollama server for --backend local (default: http://localhost:11434)",
    )
    p_transcribe.add_argument(
        "--force",
        action="store_true",
        help="Re-transcribe pages that already have text (append a new revision); "
        "default skips them",
    )
    p_transcribe.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Concurrent vision-tier requests (default: {DEFAULT_WORKERS})",
    )
    p_transcribe.add_argument(
        "--escalate-below", type=float, default=None, metavar="T",
        help="After the pass, re-transcribe model pages with fidelity < T on cloud "
        "Claude (appends a revision; needs ANTHROPIC_API_KEY). E.g. 0.9",
    )

    p_measure = sub.add_parser(
        "measure",
        help="Compare vision backends on a sample of image-only pages (read-only)",
    )
    p_measure.add_argument(
        "--case-dir", default=".", help="Case root holding lawnlord.duckdb (default: cwd)"
    )
    p_measure.add_argument(
        "--models", default=DEFAULT_LOCAL_MODEL,
        help="Comma-separated local Ollama models to compare "
        f"(default: {DEFAULT_LOCAL_MODEL})",
    )
    p_measure.add_argument(
        "--cloud", action="store_true",
        help="Also include cloud Claude in the comparison (needs ANTHROPIC_API_KEY)",
    )
    p_measure.add_argument(
        "--sample", type=int, default=10, help="Image-only pages to sample (default: 10)"
    )
    p_measure.add_argument(
        "--ollama-host", default=None, help="Ollama server (default: http://localhost:11434)"
    )

    return parser


def _build_transcribers(backend: str, model: str | None, ollama_host: str | None):
    """The exhaustive set of vision backends for one transcribe pass (ADR-0006):
    every available model reads every page. A ``CloudTranscriber`` when
    ``ANTHROPIC_API_KEY`` is set, plus a ``LocalTranscriber`` per
    ``installed_vision_models()`` entry.

    ``--backend all`` (the default) is the exhaustive set; ``--backend cloud``
    narrows to just the cloud tier; ``--backend local`` to just the local models;
    ``--model M`` pins a single model on the chosen tier (cloud unless
    ``--backend local``). Returns ``[]`` (the caller prints why and skips) when
    nothing is available."""
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    # --model pins exactly one model on the chosen tier.
    if model is not None:
        if backend == "local":
            if ollama_available(model, ollama_host):
                return [LocalTranscriber(model=model, host=ollama_host)]
            console.print(
                f"[yellow]Local model '{model}' not pulled/reachable.[/] Skipped."
            )
            return []
        if has_key:
            return [CloudTranscriber(make_client(), model=model)]
        console.print(
            "[yellow]Transcription is cloud opt-in.[/] Set ANTHROPIC_API_KEY, or "
            "use --backend local. Skipped."
        )
        return []

    transcribers: list = []
    if backend != "cloud":
        for m in installed_vision_models(ollama_host):
            transcribers.append(LocalTranscriber(model=m, host=ollama_host))
    if backend != "local" and has_key:
        transcribers.append(CloudTranscriber(make_client(), model=DEFAULT_MODEL))

    if not transcribers:
        if backend == "local":
            console.print(
                "[yellow]No local vision models installed[/] (Ollama unreachable "
                "or none pulled). Skipped."
            )
        else:
            # Default backend with no key and no local models: the cloud tier is
            # opt-in, so say so (and point at the local alternative).
            console.print(
                "[yellow]Transcription is cloud opt-in.[/] Set ANTHROPIC_API_KEY, or "
                "install a local Ollama vision model (--backend local). Skipped."
            )
    return transcribers


def _load_dotenv() -> None:
    """Source a project-local ``.env`` (cwd) so ``ANTHROPIC_API_KEY``,
    ``LAWNLORD_INTAKE``, etc. need not be exported by hand — matching how Bun
    auto-loads ``.env`` for the web viewer. Real exported env vars win
    (``override=False``); a missing ``.env`` is a silent no-op."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)


def main(argv: list[str] | None = None) -> None:
    """Entry point. Report known input errors cleanly (a clear message and exit
    1, no traceback); let unexpected errors surface for debugging."""
    _load_dotenv()
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
        # The intake is always materialized under <case-dir>/intake/<name> so the
        # case is self-contained (explode and the viewer resolve it from there).
        # A zip is extracted safely; an already-extracted dir is copied in.
        if source.is_dir():
            intake_dir = case_dir / "intake" / source.name
            if source.resolve() != intake_dir:
                shutil.copytree(source, intake_dir, dirs_exist_ok=True)
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

    if args.command == "export-exploded":
        import json

        con = open_case_db(Path(args.case_dir) / "lawnlord.duckdb", read_only=True)
        try:
            print(json.dumps(export_exploded(con)))
        finally:
            con.close()
        return

    if args.command == "explode":
        case_dir = Path(args.case_dir).resolve()
        intake_dir = find_intake_dir(case_dir)
        out_dir = case_dir / "extracted" / "pages"
        con = open_case_db(case_dir / "lawnlord.duckdb")
        apply_schema(con)
        stats = explode_case(con, intake_dir, out_dir, captured_at(intake_dir), dpi=args.dpi)
        con.close()
        table = Table(title="Exploded (filed PDFs → documents + page PNGs)")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Documents", str(stats["documents"]))
        table.add_row("Pages rendered", str(stats["pages"]))
        table.add_row("PNGs", str(out_dir))
        console.print(table)
        for m in stats["mismatches"]:
            console.print(
                f"[yellow]Page-count mismatch:[/] {m['image_id']} "
                f"declared {m['declared']} vs rendered {m['rendered']}"
            )
        if stats["skipped_images"]:
            console.print(f"[yellow]Skipped (no source PDF):[/] {len(stats['skipped_images'])}")
        console.print("[green]Done.[/]")
        return

    if args.command == "transcribe":
        case_dir = Path(args.case_dir).resolve()
        transcribers = _build_transcribers(args.backend, args.model, args.ollama_host)
        if not transcribers:
            return
        has_local = any(isinstance(t, LocalTranscriber) for t in transcribers)
        pages_dir = case_dir / "extracted" / "pages"
        con = open_case_db(case_dir / "lawnlord.duckdb")
        apply_schema(con)
        intake_dir = find_intake_dir(case_dir)
        generated_at = captured_at(intake_dir)
        stats = transcribe_case(
            con, pages_dir, generated_at, transcribers,
            force=args.force, intake_dir=intake_dir, max_workers=args.workers,
        )
        # Fidelity-gated escalation: re-transcribe the local tier's weakest pages
        # on cloud Claude (ADR-0001). Only meaningful when a local model ran.
        esc = None
        if args.escalate_below is not None:
            if not has_local:
                console.print(
                    "[yellow]--escalate-below applies to local models[/] "
                    "(this pass had none); skipping escalation."
                )
            elif not os.environ.get("ANTHROPIC_API_KEY"):
                console.print(
                    "[yellow]--escalate-below needs ANTHROPIC_API_KEY[/] for the "
                    "cloud pass; skipping escalation."
                )
            else:
                esc = escalate_case(
                    con, pages_dir, generated_at, CloudTranscriber(make_client()),
                    args.escalate_below, max_workers=args.workers,
                )
        con.close()
        models = ", ".join(t.model for t in transcribers)
        table = Table(title="Transcribed (PDF text layer + every vision model)")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Vision models", models)
        table.add_row("Pages from PDF text layer", str(stats["pdf_text"]))
        table.add_row("Pages transcribed (vision)", str(stats["pages"]))
        table.add_row("Skipped (already transcribed)", str(len(stats["skipped_existing"])))
        table.add_row("Avg fidelity (vision)", f"{stats['avg_fidelity']:.2f}")
        if esc is not None:
            table.add_row(
                f"Escalated to cloud (fidelity < {args.escalate_below})",
                f"{esc['escalated']} of {esc['candidates']}",
            )
        console.print(table)
        if stats["skipped"]:
            console.print(f"[yellow]Skipped (no PNG):[/] {len(stats['skipped'])}")
        if stats["failed"]:
            console.print(
                f"[red]Failed (vision error after retries):[/] {len(stats['failed'])}"
            )
        console.print("[green]Done.[/]")
        return

    if args.command == "measure":
        case_dir = Path(args.case_dir).resolve()
        transcribers: dict = {}
        host = args.ollama_host
        for m in (s.strip() for s in args.models.split(",") if s.strip()):
            if ollama_available(m, host):
                transcribers[m] = LocalTranscriber(model=m, host=host)
            else:
                console.print(f"[yellow]Skipping[/] local model '{m}' (not pulled/reachable).")
        if args.cloud:
            if os.environ.get("ANTHROPIC_API_KEY"):
                transcribers[f"cloud:{DEFAULT_MODEL}"] = CloudTranscriber(make_client())
            else:
                console.print("[yellow]--cloud set but no ANTHROPIC_API_KEY[/] — omitting cloud.")
        if not transcribers:
            console.print("[red]No backends available to measure.[/]")
            raise SystemExit(1)
        pages_dir = case_dir / "extracted" / "pages"
        con = open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
        intake_dir = find_intake_dir(case_dir)
        try:
            result = measure_case(con, pages_dir, transcribers, sample=args.sample,
                                  intake_dir=intake_dir)
        finally:
            con.close()
        labels = result["labels"]
        table = Table(title=f"Backend comparison ({result['sampled']} image-only pages)")
        table.add_column("Backend")
        table.add_column("Avg fidelity", justify="right")
        for t in (0.7, 0.8, 0.9, 0.95):
            table.add_column(f"<{t}", justify="right")
        for label in labels:
            row = [label, f"{result['avg_fidelity'][label]:.3f}"]
            row += [f"{result['escalation_fraction'][label][t]:.0%}" for t in (0.7, 0.8, 0.9, 0.95)]
            table.add_row(*row)
        console.print(table)
        console.print(
            "[dim]Columns <T = share of sampled pages that backend reads below "
            "fidelity T (the fraction that would escalate at that threshold).[/]"
        )
        return
