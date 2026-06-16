"""Human-facing output: the --dry-run archive report and the
--emit-boundary-template draft writer.

report_archive() renders the read-only inspection as Rich tables;
write_boundary_template() emits a reviewable manual-boundary draft from the
current detector output (never read back by detection).
"""

from __future__ import annotations

from pathlib import Path

from rich.table import Table

from .analysis_schema import write_json
from .boundaries import REVIEW_CONFIDENCE_THRESHOLD, confidence_distribution
from .console import console
from .hashing import now_iso
from .models import SectionBoundary


def report_archive(report: dict) -> None:
    console.print(f"[bold]Archive:[/] {report['zipPath']}")
    console.print(f"[bold]Archive sha256:[/] {report['zipSha256']}")

    table = Table(title="Documents / Source PDFs in Archive")
    table.add_column("#", justify="right")
    table.add_column("Path in ZIP")
    table.add_column("Pages", justify="right")
    table.add_column("Sections", justify="right")
    table.add_column("SHA-256 (12)", justify="left")
    table.add_column("Submission slug")
    table.add_column("Document slug")

    total_pages = 0
    total_sections = 0
    unreadable = 0
    all_sections: list[SectionBoundary] = []

    for idx, entry in enumerate(report["pdfEntries"], start=1):
        if entry.page_count is None:
            unreadable += 1
            pages = "unreadable"
            console.print(f"[red]Warning:[/] could not read {entry.zip_path}: {entry.error}")
        else:
            total_pages += entry.page_count
            pages = str(entry.page_count)

        total_sections += len(entry.sections)
        all_sections.extend(entry.sections)

        table.add_row(
            str(idx),
            entry.zip_path,
            pages,
            str(len(entry.sections)),
            (entry.sha256 or "-")[:12],
            entry.submission_slug,
            entry.document_slug,
        )

    console.print(table)

    summary = Table(title="Archive Summary")
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Total zip entries", str(report["totalEntries"]))
    summary.add_row("PDF documents", str(len(report["pdfEntries"])))
    summary.add_row("Total pages (readable PDFs)", str(total_pages))
    summary.add_row("Unreadable PDFs", str(unreadable))
    summary.add_row("Proposed sections (total)", str(total_sections))
    for key, count in confidence_distribution(all_sections).items():
        summary.add_row(f"Sections @ confidence {key}", str(count))
    summary.add_row("Nested ZIPs (not expanded)", str(len(report["nestedZips"])))
    summary.add_row("Suspicious entries (path traversal)", str(len(report["suspiciousEntries"])))
    console.print(summary)

    if report["nestedZips"]:
        console.print("[yellow]Nested ZIPs found (reported only, not expanded):[/]")
        for name in report["nestedZips"]:
            console.print(f"  - {name}")

    if report["suspiciousEntries"]:
        console.print("[red]Suspicious entries (would escape extraction root; skipped):[/]")
        for name in report["suspiciousEntries"]:
            console.print(f"  - {name}")


def write_boundary_template(report: dict, output_path: Path) -> dict:
    """Emit a reviewable manual-boundary draft from the current detector
    output. The draft is generated and never read by detection; a human
    reviews it and copies the result to src/filings/bundle-boundaries.json (the
    live file) to activate manual boundaries.

    Documents are keyed by sourceZipPath because manual_entries_for()
    matches on sourceZipPath first (with originalFilename as its fallback).
    Output is deterministic: document keys sorted by sourceZipPath, stable
    field order, indent=2. No page text, legal analysis, or corpus paths —
    only boundary facts plus blank reviewAction/reviewNotes placeholders.
    """
    documents: dict = {}
    for entry in sorted(report["pdfEntries"], key=lambda e: e.zip_path):
        if entry.page_count is None or entry.sha256 is None:
            continue

        sections = []
        doc_needs_review = False
        for index, section in enumerate(entry.sections, start=1):
            needs_review = section.confidence < REVIEW_CONFIDENCE_THRESHOLD
            doc_needs_review = doc_needs_review or needs_review
            sections.append(
                {
                    "sectionIndex": index,
                    "title": section.title,
                    "startPage": section.start_page,
                    "endPage": section.end_page,
                    "pageCount": section.page_count,
                    "documentFamily": section.document_family,
                    "confidence": section.confidence,
                    "detectionTier": section.detection_tier,
                    "reason": section.reason,
                    "needsHumanReview": needs_review,
                    "reviewAction": "",
                    "reviewNotes": "",
                }
            )

        documents[entry.zip_path] = {
            "sourceZipPath": entry.zip_path,
            "originalFilename": entry.filename,
            "submissionSlug": entry.submission_slug,
            "documentSlug": entry.document_slug,
            "sha256": entry.sha256,
            "pageCount": entry.page_count,
            "detectedSectionCount": len(entry.sections),
            "needsHumanReview": doc_needs_review,
            "sections": sections,
        }

    template = {
        "version": 1,
        "generatedAt": now_iso(),
        "sourceArchive": {
            "zipPath": str(report["zipPath"]),
            "zipSha256": report["zipSha256"],
            "pdfCount": len(documents),
            "totalPageCount": sum(d["pageCount"] for d in documents.values()),
        },
        "instructions": [
            "This is a generated draft. Review and copy to src/filings/bundle-boundaries.json to make it live.",
            "Do not edit generated output in place as source of truth.",
            "Manual boundaries must cover pages 1..pageCount without gaps or overlaps.",
            "startPage and endPage are 1-based source PDF page numbers.",
            "src/filings/bundle-boundaries.generated.json is ignored by git; src/filings/bundle-boundaries.json is the live reviewed file.",
        ],
        "documents": documents,
    }
    write_json(output_path, template)
    return template
