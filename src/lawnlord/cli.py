"""Command-line entry point: argument parsing and run dispatch.

This is the orchestration layer only — it resolves the zip, loads the manual
boundaries and curation overlay, and dispatches to inspect/report (--dry-run),
boundary-template emit (--emit-boundary-template), or a real corpus build. All
the real work lives in the sibling modules.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.table import Table

from .archive import inspect_archive
from .boundaries import load_manual_boundaries
from .console import console
from .corpus import write_corpus
from .curation import load_curation
from .paths import (
    DEFAULT_CORPUS_DIR,
    FILINGS_DIR,
    GENERATED_BOUNDARIES_FILENAME,
    MANUAL_BOUNDARIES_FILENAME,
    resolve_zip_path,
)
from .reporting import report_archive, write_boundary_template


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Model the legal source archive as Archive/Packet -> Submission ->"
            " Document/Source PDF -> Section -> Page, and explode every"
            " document into section PDFs, page PDFs, extracted page text,"
            " section metadata, a document toc.json, and page analysis stubs."
        )
    )
    parser.add_argument(
        "zip_path",
        nargs="?",
        default=None,
        help="Path to the source ZIP (default: search known locations)",
    )
    parser.add_argument(
        "--corpus-dir",
        default=None,
        help=(
            "Output corpus directory (default: the corpus/ folder next to"
            " this script, regardless of the caller's cwd)"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild existing submission folders",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect the archive and report; never writes output",
    )
    parser.add_argument(
        "--emit-boundary-template",
        action="store_true",
        help=(
            "Write a generated manual-boundary draft"
            f" ({GENERATED_BOUNDARIES_FILENAME}) from the detected boundaries"
            " and exit; never writes the corpus or the live boundary file"
        ),
    )

    args = parser.parse_args()

    zip_path = resolve_zip_path(args.zip_path)
    console.print(f"[bold]Resolved ZIP:[/] {zip_path}")

    manual_boundaries = load_manual_boundaries()
    curation = load_curation()

    if args.emit_boundary_template:
        output_path = FILINGS_DIR / GENERATED_BOUNDARIES_FILENAME
        if output_path.exists():
            console.print(
                f"[yellow]Overwriting existing generated draft (not live):[/] {output_path}"
            )
        # The template is a draft of the *automatic* detector output for
        # human review — never the live manual baseline, which would make
        # the draft circular once bundle-boundaries.json exists.
        template = write_boundary_template(
            inspect_archive(zip_path, {}), output_path
        )
        documents = template["documents"]
        section_total = sum(d["detectedSectionCount"] for d in documents.values())
        review_total = sum(
            1
            for d in documents.values()
            for s in d["sections"]
            if s["needsHumanReview"]
        )
        console.print(f"[bold]Boundary template written:[/] {output_path}")
        console.print(f"Documents: {len(documents)}")
        console.print(f"Detected sections: {section_total}")
        console.print(f"Sections needing human review: {review_total}")
        console.print(
            "[yellow]This file is a generated draft, not live. Review it and copy"
            f" the result to {MANUAL_BOUNDARIES_FILENAME} to activate manual"
            " boundaries.[/]"
        )
        return

    if args.dry_run:
        report_archive(inspect_archive(zip_path, manual_boundaries))
        return

    # Default output goes to dist/corpus (generated, gitignored) so a build run
    # cannot accidentally create a stray root-level corpus/. An explicit
    # --corpus-dir is honored exactly as provided (resolved from the cwd).
    if args.corpus_dir:
        corpus_dir = Path(args.corpus_dir).resolve()
    else:
        corpus_dir = DEFAULT_CORPUS_DIR
    console.print(f"[bold]Corpus:[/] {corpus_dir}")

    manifest = write_corpus(
        zip_path, corpus_dir, args.force, manual_boundaries, curation
    )

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
    table.add_row(
        "Analysis files discovered",
        str(preservation["reviewedAnalysisDiscovered"]),
    )
    table.add_row(
        "Reviewed analysis indexed", str(preservation["reviewedAnalysisIndexed"])
    )
    table.add_row(
        "Reviewed analysis preserved", str(preservation["reviewedAnalysisPreserved"])
    )
    table.add_row(
        "Invalid analysis skipped", str(preservation["reviewedAnalysisInvalid"])
    )
    table.add_row(
        "Duplicate preservation keys", str(preservation["reviewedAnalysisDuplicates"])
    )
    table.add_row(
        "Reviewed analysis unmatched", str(preservation["reviewedAnalysisUnmatched"])
    )
    curation_stats = manifest["curation"]
    table.add_row(
        "Curated documents applied", str(curation_stats["documentsApplied"])
    )
    table.add_row("Curated sections applied", str(curation_stats["sectionsApplied"]))
    if curation_stats["loaded"]:
        table.add_row("Curation file", curation_stats["path"])
    table.add_row("Manifest", str(corpus_dir / "manifest.json"))
    console.print(table)
    console.print("[green]Done.[/]")
