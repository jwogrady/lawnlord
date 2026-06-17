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


def _pdf_entry(
    name: str,
    data: bytes,
    manual_boundaries: dict,
    used_submission_slugs: set[str],
    used_document_slugs: set[str],
    source_path: str = "",
) -> PdfEntry:
    """Build one PdfEntry from a PDF's bytes (shared by the ZIP and folder
    front-ends): hash it, read its page count, and propose section boundaries.
    Read errors are captured on the entry, never raised."""
    stem = Path(name).stem
    filename = Path(name).name
    page_count: int | None = None
    digest: str | None = None
    sections: list[SectionBoundary] = []
    error = ""

    try:
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
    return PdfEntry(
        zip_path=name,
        filename=filename,
        page_count=page_count,
        sha256=digest,
        # One submission per source PDF for now; the submission/document
        # model allows curated grouping later.
        submission_slug=unique_slug(stem, fallback, used_submission_slugs),
        document_slug=unique_slug(stem, fallback, used_document_slugs),
        error=error,
        sections=sections,
        source_path=source_path,
    )


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

            try:
                data = z.read(name)
            except Exception as exc:
                pdf_entries.append(
                    PdfEntry(
                        zip_path=name,
                        filename=Path(name).name,
                        page_count=None,
                        sha256=None,
                        submission_slug=unique_slug(
                            Path(name).stem, sha256_bytes(name.encode())[:8],
                            used_submission_slugs,
                        ),
                        document_slug=unique_slug(
                            Path(name).stem, sha256_bytes(name.encode())[:8],
                            used_document_slugs,
                        ),
                        error=str(exc),
                    )
                )
                continue

            pdf_entries.append(
                _pdf_entry(
                    name, data, manual_boundaries,
                    used_submission_slugs, used_document_slugs,
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


def inspect_folder(folder: Path, manual_boundaries: dict | None = None) -> dict:
    """Read-only inspection of a folder of loose PDFs (folder source mode).

    Reads ``*.pdf`` directly under ``folder`` in sorted order (deterministic),
    proposing section boundaries per PDF. Returns the same report shape as
    :func:`inspect_archive`; the archive digest is a stable hash of the sorted
    ``filename:sha256`` pairs (not a ZIP byte hash), so it is reproducible.
    """
    folder = Path(folder)
    manual_boundaries = manual_boundaries or {}
    pdf_entries: list[PdfEntry] = []
    used_submission_slugs: set[str] = set()
    used_document_slugs: set[str] = set()

    # Case-insensitive on the extension, matching the ZIP front-end (which
    # lower-cases before checking) — a portal-supplied ``.PDF`` must not vanish.
    pdfs = sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
    )
    for pdf in pdfs:
        name = pdf.name
        data = pdf.read_bytes()
        pdf_entries.append(
            _pdf_entry(
                name, data, manual_boundaries,
                used_submission_slugs, used_document_slugs,
                source_path=str(pdf.resolve()),
            )
        )

    digest_basis = "\n".join(
        f"{e.filename}:{e.sha256 or ''}" for e in pdf_entries
    )
    return {
        "zipPath": folder,
        "zipSha256": sha256_bytes(digest_basis.encode()),
        "totalEntries": len(pdfs),
        "pdfEntries": pdf_entries,
        "nestedZips": [],
        "suspiciousEntries": [],
    }


def inspect_source(source: Path, manual_boundaries: dict | None = None) -> dict:
    """Inspect either a ZIP packet or a folder of loose PDFs, dispatching on
    what ``source`` is (a directory -> folder mode; otherwise ZIP mode)."""
    return (
        inspect_folder(source, manual_boundaries)
        if Path(source).is_dir()
        else inspect_archive(source, manual_boundaries)
    )
