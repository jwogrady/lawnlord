"""Command-line entry point: subcommands over an intake folder.

    lawnlord start [root]              scaffold an intake folder
    lawnlord report [root]             read-only archive/section report (no writes)
    lawnlord build [root]              build the corpus from the intake packet
    lawnlord emit-boundaries [root]    write a reviewable manual-boundary draft
    lawnlord index [intake]            explode + ingest + index into DuckDB
    lawnlord pack [intake]             package case.json + filings as the source of truth
    lawnlord assemble [intake]         reassemble images into one master PDF (round-trip proof)
    lawnlord query                     read-only search over the index (with provenance)

``root`` defaults to the current directory; lawnlord resolves the intake/corpus
locations from it (honoring an optional lawnlord.toml). All the real work lives
in the sibling modules — this layer only parses args and dispatches.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.table import Table

from .archive import inspect_source
from .assemble import assemble_case
from .boundaries import load_manual_boundaries
from .console import console
from .corpus import write_corpus
from .curation import load_curation
from .db import apply_schema, open_case_db
from .index import index_corpus
from .ingest import ingest_case
from .intake import load_intake, resolve_packet, scaffold
from .ocr import make_lazy_ocr
from .pack import pack_case
from .query import (
    images_by_event,
    images_by_party,
    images_by_phase,
    needs_review_documents,
    search_text,
)
from .reporting import report_archive, write_boundary_template
from .workspace import Case


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Project root containing the intake (default: current directory)",
    )


def _add_packet(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--packet",
        default=None,
        help=(
            "Explicit source: a ZIP, or a directory of loose PDFs "
            "(default: the single *.zip in the intake dir)"
        ),
    )


def _ocr_for(args):
    """The OCR backend for a build. OCR is **on by default** so every page is
    searchable; it is lazy (the engine loads only when a text-less page is found)
    and degrades gracefully when the optional 'ocr' extra is missing. ``--no-ocr``
    disables it (the fast path); ``--gpu`` runs the engine on CUDA."""
    if getattr(args, "no_ocr", False):
        return None
    if getattr(args, "gpu", False):
        return make_lazy_ocr(use_gpu=True)
    return make_lazy_ocr()


def _resolve_source(intake, explicit) -> Path:
    """Resolve the source to explode: an explicit directory of PDFs is used
    as-is (folder mode); otherwise fall back to ZIP packet resolution."""
    if explicit and Path(explicit).is_dir():
        return Path(explicit).resolve()
    return resolve_packet(intake, explicit)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lawnlord",
        description=(
            "Explode a legal court-record packet into a five-level corpus"
            " (archive -> submission -> document -> section -> page)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="Scaffold an intake folder")
    _add_root(p_start)
    p_start.add_argument(
        "--force", action="store_true", help="Overwrite an existing config / intake README"
    )

    p_report = sub.add_parser(
        "report", help="Read-only archive/section report; never writes"
    )
    _add_root(p_report)
    _add_packet(p_report)

    p_build = sub.add_parser("build", help="Build the corpus from the intake packet")
    _add_root(p_build)
    _add_packet(p_build)
    p_build.add_argument(
        "--corpus-dir", default=None, help="Override the output corpus directory"
    )
    p_build.add_argument(
        "--force", action="store_true", help="Rebuild existing submission folders"
    )
    p_build.add_argument(
        "--no-ocr", action="store_true",
        help="Disable OCR (the fast path); scanned pages stay empty + flagged for review",
    )
    p_build.add_argument(
        "--gpu", action="store_true",
        help="Run OCR on the GPU (CUDA) when available",
    )

    p_emit = sub.add_parser(
        "emit-boundaries",
        help="Write a generated manual-boundary draft into the intake dir; never writes the corpus",
    )
    _add_root(p_emit)
    _add_packet(p_emit)

    p_index = sub.add_parser(
        "index",
        help="Explode a case intake folder's filings and index it into DuckDB",
    )
    p_index.add_argument(
        "intake",
        nargs="?",
        default=".",
        help="Provider intake folder (e.g. .../intake/ody) with case JSON + filings/",
    )
    p_index.add_argument(
        "--case-dir", default=None, help="Output root for the corpus + DuckDB (default: cwd)"
    )
    p_index.add_argument(
        "--force", action="store_true", help="Rebuild existing submission folders"
    )
    p_index.add_argument(
        "--no-ocr", action="store_true",
        help="Disable OCR (the fast path); scanned pages stay empty + flagged for review",
    )
    p_index.add_argument(
        "--gpu", action="store_true",
        help="Run OCR on the GPU (CUDA) when available",
    )

    p_pack = sub.add_parser(
        "pack",
        help="Package a case as the source of truth: case.json (all data) + filings (all files) in one zip",
    )
    p_pack.add_argument(
        "intake",
        nargs="?",
        default=".",
        help="Provider intake folder (e.g. .../intake/combo) with case JSON + filings/",
    )
    p_pack.add_argument(
        "-o", "--output", default=None,
        help="Output zip path (default: <caseNumber>.zip in the current directory)",
    )

    p_assemble = sub.add_parser(
        "assemble",
        help="Reassemble the case's images into one master PDF (the lossless round-trip proof)",
    )
    p_assemble.add_argument(
        "intake",
        nargs="?",
        default=".",
        help="Provider intake folder (e.g. .../intake/combo) with case JSON + filings/",
    )
    p_assemble.add_argument(
        "-o", "--output", default=None,
        help="Output master PDF path (default: <caseNumber>-master.pdf in the current directory)",
    )

    p_query = sub.add_parser(
        "query", help="Read-only search over the case index (with provenance)"
    )
    p_query.add_argument(
        "--case-dir", default=".", help="Case output root holding lawnlord.duckdb (default: cwd)"
    )
    p_query.add_argument("--text", default=None, help="Full-text search over page text")
    p_query.add_argument(
        "--needs-review", action="store_true", help="Sections flagged for human review"
    )
    p_query.add_argument("--event", default=None, help="Documents for a docket event type")
    p_query.add_argument("--phase", default=None, help="Documents filed in a docket phase")
    p_query.add_argument("--party", default=None, help="Documents tied to a party")
    p_query.add_argument("--limit", type=int, default=50, help="Max --text results")

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "query":
        _run_query(args)
        return

    if args.command == "pack":
        case = Case.from_intake(args.intake)
        out_zip = Path(args.output) if args.output else Path.cwd() / f"{case.case_slug}.zip"
        stats = pack_case(case, out_zip)
        table = Table(title="Packed source of truth")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Case", case.case_number)
        table.add_row("Provider", stats["provider"])
        table.add_row("Documents", str(stats["documents"]))
        table.add_row("Files packed", str(stats["packed"]))
        table.add_row("Files missing", str(len(stats["missing"])))
        table.add_row("Zip", stats["out_zip"])
        console.print(table)
        for rel in stats["missing"]:
            console.print(f"[yellow]Missing source PDF (not packed):[/] {rel}")
        console.print("[green]Done.[/]")
        return

    if args.command == "assemble":
        case = Case.from_intake(args.intake)
        out_pdf = (
            Path(args.output) if args.output
            else Path.cwd() / f"{case.case_slug}-master.pdf"
        )
        stats = assemble_case(case, out_pdf)
        table = Table(title="Reassembled master PDF")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Case", case.case_number)
        table.add_row("Images", str(stats["images"]))
        table.add_row("Pages", str(stats["pages"]))
        table.add_row("Outline entries", str(stats["outline_entries"]))
        table.add_row(
            "Embedded attachments",
            f"{stats['embedded_attachments']}/{stats['embedded_source']} carried",
        )
        table.add_row(
            "Annotations",
            f"{stats['annotations_master']}/{stats['annotations_source']} preserved",
        )
        table.add_row("Missing images", str(len(stats["missing"])))

        def _flag(v):
            return "[green]yes[/]" if v else "[red]NO[/]" if v is False else "n/a"

        table.add_row("Text-lossless round-trip", _flag(stats["text_lossless"]))
        vis = stats["visual_lossless"]
        table.add_row(
            "Visual-lossless round-trip",
            _flag(vis) + (f" (Δ {stats['visual_worst_diff']})" if vis is not None else ""),
        )
        table.add_row("Master PDF", stats["out_pdf"])
        table.add_row("Manifest", stats["manifest"])
        console.print(table)
        for rel in stats["missing"]:
            console.print(f"[yellow]Missing source image (not assembled):[/] {rel}")
        console.print("[green]Done.[/]")
        return

    if args.command == "index":
        case = Case.from_intake(args.intake, case_dir=args.case_dir)
        console.print(f"[bold]Case:[/] {case.case_number}  [dim]({case.intake_dir})[/]")
        manual_boundaries = load_manual_boundaries(
            case.intake_dir / "bundle-boundaries.json"
        )
        curation = load_curation(case.intake_dir / "corpus-curation.json")
        manifest = write_corpus(
            case.filings_dir, case.corpus_dir, args.force, manual_boundaries, curation,
            ocr=_ocr_for(args),
        )
        generated_at = manifest["generatedAt"]
        con = open_case_db(case.duckdb_path)
        apply_schema(con)
        ingest_stats = ingest_case(con, case, generated_at)
        index_stats = index_corpus(con, case, case.corpus_dir, generated_at)
        con.close()
        _print_index_summary(case, ingest_stats, index_stats)
        return

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
            f"Drop the packet ZIP in [bold]{intake.intake_dir}[/], then run"
            " [bold]lawnlord build[/]."
        )
        return

    intake = load_intake(args.root)

    if args.command == "report":
        packet = _resolve_source(intake, args.packet)
        manual = load_manual_boundaries(intake.manual_boundaries_path)
        report_archive(inspect_source(packet, manual))
        return

    if args.command == "emit-boundaries":
        packet = _resolve_source(intake, args.packet)
        output_path = intake.generated_boundaries_path
        if output_path.exists():
            console.print(
                f"[yellow]Overwriting existing generated draft (not live):[/] {output_path}"
            )
        # A draft of the *automatic* detector output for human review — never
        # the live manual baseline, which would make the draft circular once
        # the manual boundaries file exists.
        template = write_boundary_template(inspect_source(packet, {}), output_path)
        documents = template["documents"]
        section_total = sum(d["detectedSectionCount"] for d in documents.values())
        review_total = sum(
            1 for d in documents.values() for s in d["sections"] if s["needsHumanReview"]
        )
        console.print(f"[bold]Boundary template written:[/] {output_path}")
        console.print(f"Documents: {len(documents)}")
        console.print(f"Detected sections: {section_total}")
        console.print(f"Sections needing human review: {review_total}")
        console.print(
            "[yellow]This is a generated draft, not live. Review it and save the result as"
            f" {intake.manual_boundaries_path.name} in the intake dir to activate manual"
            " boundaries.[/]"
        )
        return

    if args.command == "build":
        packet = _resolve_source(intake, args.packet)
        console.print(f"[bold]Packet:[/] {packet}")
        manual_boundaries = load_manual_boundaries(intake.manual_boundaries_path)
        curation = load_curation(intake.curation_path)

        corpus_dir = Path(args.corpus_dir).resolve() if args.corpus_dir else intake.corpus_dir
        console.print(f"[bold]Corpus:[/] {corpus_dir}")

        manifest = write_corpus(
            packet,
            corpus_dir,
            args.force,
            manual_boundaries,
            curation,
            curation_path=intake.curation_path,
            ocr=_ocr_for(args),
        )
        _print_build_summary(manifest, corpus_dir)
        return


def _render_rows(title: str, rows: list[dict]) -> None:
    if not rows:
        console.print(f"[yellow]No results for {title}.[/]")
        return
    table = Table(title=title)
    for col in rows[0]:
        table.add_column(col)
    for row in rows:
        table.add_row(*[("" if v is None else str(v)) for v in row.values()])
    console.print(table)
    console.print(f"[dim]{len(rows)} result(s)[/]")


def _run_query(args) -> None:
    db_path = Path(args.case_dir) / "lawnlord.duckdb"
    con = open_case_db(db_path, read_only=True)
    try:
        if args.text is not None:
            _render_rows(f"text: {args.text!r}", search_text(con, args.text, args.limit))
        elif args.needs_review:
            _render_rows("needs review", needs_review_documents(con))
        elif args.phase is not None:
            _render_rows(f"phase: {args.phase}", images_by_phase(con, args.phase))
        elif args.event is not None:
            _render_rows(f"event: {args.event}", images_by_event(con, args.event))
        elif args.party is not None:
            _render_rows(f"party: {args.party}", images_by_party(con, args.party))
        else:
            console.print(
                "[red]Specify a filter:[/] --text / --needs-review / --phase / --event / --party"
            )
    finally:
        con.close()


def _print_index_summary(case, ingest_stats: dict, index_stats: dict) -> None:
    table = Table(title="Case Index Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Case", case.case_number)
    table.add_row("Parties", str(ingest_stats["parties"]))
    table.add_row("Events", str(ingest_stats["events"]))
    table.add_row("Images (filed PDFs)", str(ingest_stats["images"]))
    table.add_row("Image↔event links", str(ingest_stats["image_events"]))
    table.add_row("Documents (within images)", str(index_stats["documents"]))
    table.add_row("Chunks (pages)", str(index_stats["chunks"]))
    table.add_row(
        "Full-text index (BM25)",
        "[green]built[/]" if index_stats.get("fts") else "[yellow]LIKE fallback[/]",
    )
    table.add_row("Page-count mismatches", str(len(index_stats["mismatches"])))
    table.add_row("Un-docketed images", str(index_stats["orphan_images"]))
    table.add_row("DuckDB", str(case.duckdb_path))
    console.print(table)
    if ingest_stats["skipped_images"]:
        console.print(
            f"[yellow]Skipped (no source PDF):[/] {len(ingest_stats['skipped_images'])}"
        )
    if index_stats["orphan_images"]:
        console.print(
            f"[yellow]Un-docketed images indexed (not in filings.json):[/]"
            f" {index_stats['orphan_images']}"
        )
    for m in index_stats["mismatches"]:
        console.print(
            f"[yellow]Page-count mismatch:[/] {m['image_id']} "
            f"declared {m['declared']} vs actual {m['actual']}"
        )
    console.print("[green]Done.[/]")


def _print_build_summary(manifest: dict, corpus_dir: Path) -> None:
    document_count = sum(s["documentCount"] for s in manifest["submissions"])
    page_count = sum(s["pageCount"] for s in manifest["submissions"])
    section_count = sum(
        d.get("sectionCount", 0)
        for s in manifest["submissions"]
        for d in s["documents"]
    )

    table = Table(title="Corpus Model Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Archive", manifest["archive"]["archiveId"])
    table.add_row("Submissions", str(len(manifest["submissions"])))
    table.add_row("Documents", str(document_count))
    table.add_row("Pages", str(page_count))
    table.add_row("Proposed sections", str(section_count))
    table.add_row("Skipped entries", str(len(manifest["skipped"])))
    preservation = manifest["reviewPreservation"]
    table.add_row("Analysis files discovered", str(preservation["reviewedAnalysisDiscovered"]))
    table.add_row("Reviewed analysis indexed", str(preservation["reviewedAnalysisIndexed"]))
    table.add_row("Reviewed analysis preserved", str(preservation["reviewedAnalysisPreserved"]))
    table.add_row("Invalid analysis skipped", str(preservation["reviewedAnalysisInvalid"]))
    table.add_row("Duplicate preservation keys", str(preservation["reviewedAnalysisDuplicates"]))
    table.add_row("Reviewed analysis unmatched", str(preservation["reviewedAnalysisUnmatched"]))
    curation_stats = manifest["curation"]
    table.add_row("Curated documents applied", str(curation_stats["documentsApplied"]))
    table.add_row("Curated sections applied", str(curation_stats["sectionsApplied"]))
    if curation_stats["loaded"]:
        table.add_row("Curation file", curation_stats["path"])
    table.add_row("Manifest", str(corpus_dir / "manifest.json"))
    console.print(table)
    console.print("[green]Done.[/]")
