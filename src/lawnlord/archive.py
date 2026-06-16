"""Read-only inspection of the source packet (Archive / Packet level).

inspect_archive() walks the zip, reads each PDF, proposes section boundaries,
and returns the structured report both --dry-run and a real build consume.
Nothing is extracted or written here; zip entries are never trusted by name.
"""

from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath

import fitz

from .boundaries import detect_sections_in_doc, manual_entries_for
from .hashing import sha256_bytes, sha256_file
from .models import PdfEntry, SectionBoundary, unique_slug


def is_suspicious_entry(name: str) -> bool:
    """Flag zip entries that would escape an extraction root (path traversal)."""
    pure = PurePosixPath(name.replace("\\", "/"))
    return pure.is_absolute() or ".." in pure.parts


def inspect_archive(zip_path: Path, manual_boundaries: dict | None = None) -> dict:
    """Read-only inspection of the source packet, including proposed section
    boundaries per PDF. Nothing is extracted or written."""
    manual_boundaries = manual_boundaries or {}
    pdf_entries: list[PdfEntry] = []
    nested_zips: list[str] = []
    suspicious: list[str] = []
    used_submission_slugs: set[str] = set()
    used_document_slugs: set[str] = set()

    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.infolist() if not m.is_dir()]

        for member in members:
            name = member.filename

            if is_suspicious_entry(name):
                suspicious.append(name)
                continue

            lower = name.lower()
            if lower.endswith(".zip"):
                nested_zips.append(name)
                continue
            if not lower.endswith(".pdf"):
                continue

            stem = Path(name).stem
            filename = Path(name).name
            page_count: int | None = None
            digest: str | None = None
            sections: list[SectionBoundary] = []
            error = ""

            try:
                data = z.read(name)
                digest = sha256_bytes(data)
                with fitz.open(stream=data, filetype="pdf") as doc:
                    page_count = doc.page_count
                    sections = detect_sections_in_doc(
                        doc,
                        filename,
                        stem,
                        manual_entries_for(manual_boundaries, name, filename),
                    )
            except Exception as exc:
                error = str(exc)

            fallback = (digest or sha256_bytes(name.encode()))[:8]
            pdf_entries.append(
                PdfEntry(
                    zip_path=name,
                    filename=filename,
                    page_count=page_count,
                    sha256=digest,
                    # One submission per source PDF for now; the
                    # submission/document model allows curated grouping later.
                    submission_slug=unique_slug(stem, fallback, used_submission_slugs),
                    document_slug=unique_slug(stem, fallback, used_document_slugs),
                    error=error,
                    sections=sections,
                )
            )

        total_entries = len(members)

    return {
        "zipPath": zip_path,
        "zipSha256": sha256_file(zip_path),
        "totalEntries": total_entries,
        "pdfEntries": pdf_entries,
        "nestedZips": nested_zips,
        "suspiciousEntries": suspicious,
    }
