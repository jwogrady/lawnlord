"""Command-line entry point: subcommands over an intake folder.

    lawnlord start [root]              scaffold an intake folder
    lawnlord report [root]             read-only archive/section report (no writes)
    lawnlord build [root]              build the corpus from the intake packet
    lawnlord emit-boundaries [root]    write a reviewable manual-boundary draft

``root`` defaults to the current directory; lawnlord resolves the intake/corpus
locations from it (honoring an optional lawnlord.toml). All the real work lives
in the sibling modules — this layer only parses args and dispatches.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.table import Table

from .archive import inspect_source
from .boundaries import load_manual_boundaries
from .console import console
from .corpus import write_corpus
from .curation import load_curation
from .intake import load_intake, resolve_packet, scaffold
from .reporting import report_archive, write_boundary_template


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

    p_emit = sub.add_parser(
        "emit-boundaries",
        help="Write a generated manual-boundary draft into the intake dir; never writes the corpus",
    )
    _add_root(p_emit)
    _add_packet(p_emit)

    return parser


def main(argv: list[str] | None = None) -> None:
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
        )
        _print_build_summary(manifest, corpus_dir)
        return


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
