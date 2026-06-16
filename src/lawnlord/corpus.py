"""Corpus writer: explode documents and assemble the on-disk model.

explode_document() writes all section/page artifacts for one document;
write_corpus() walks the archive, writes the archive/submission/document
metadata and manifest, applies curation, and preserves reviewed analysis on
--force. Paths recorded in metadata are relative to the document folder and
re-anchored to the corpus root in the manifest.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import fitz
from slugify import slugify

from .analysis_schema import legal_analysis_placeholders, write_json
from .archive import inspect_archive
from .boundaries import (
    REVIEW_CONFIDENCE_THRESHOLD,
    SectionBoundary,
    confidence_distribution,
    section_summary,
)
from .console import console
from .curation import (
    ALLOWED_CURATED_FIELDS,
    apply_metadata_overlay,
    document_curation_for,
    section_curation_for,
)
from .hashing import now_iso, sha256_file
from .preservation import apply_preserved_analysis, collect_reviewed_analysis


def explode_document(
    source_doc: fitz.Document,
    document_dir: Path,
    ids: dict,
    sections: list[SectionBoundary],
    boundary_summaries: list[dict],
    preservation_index: dict | None = None,
    generated_at: str = "",
    document_curation: dict | None = None,
    curation_defaults: dict | None = None,
) -> tuple[list[dict], dict, dict]:
    """Explode one Document/Source PDF into section PDFs, page PDFs, page
    text, page analysis stubs, per-section metadata, and a document toc.json.

    All artifact paths recorded in metadata/toc are relative to the document
    folder. Every page artifact carries both pageNumber (within its section)
    and sourcePageNumber (within the original source PDF — the citable one).

    When a preservation_index (from collect_reviewed_analysis) is given,
    previously reviewed page analysis is re-applied onto the fresh stubs.
    When document_curation/curation_defaults are given, allowed curated
    metadata fields are overlaid onto section metadata, enriched records,
    and toc entries — never onto page analysis legal fields.

    Returns (section summaries enriched with artifact paths and text stats,
    the toc payload, explosion stats).
    """
    sections_root = document_dir / "sections"
    toc_sections: list[dict] = []
    enriched: list[dict] = []
    preserved_count = 0
    curated_section_count = 0
    document_curation = document_curation or {}
    curation_defaults = curation_defaults or {}

    for index, (section, summary) in enumerate(
        zip(sections, boundary_summaries), start=1
    ):
        # Folder names are index-prefixed so listing order matches reading
        # order and stays unique even if two slugs ever collided.
        section_rel = f"sections/{index:03d}-{section.slug}"
        section_dir = sections_root / f"{index:03d}-{section.slug}"
        for sub in ("pages", "text", "analysis"):
            (section_dir / sub).mkdir(parents=True, exist_ok=True)

        section_pdf_rel = f"{section_rel}/section.pdf"
        empty_text_pages = 0
        toc_pages: list[dict] = []

        with fitz.open() as section_pdf:
            section_pdf.insert_pdf(
                source_doc,
                from_page=section.start_page - 1,
                to_page=section.end_page - 1,
            )
            section_pdf.save(document_dir / section_pdf_rel)

            for page_number in range(1, section.page_count + 1):
                source_page_number = section.start_page + page_number - 1
                stem = f"page-{page_number:03d}"
                page_pdf_rel = f"{section_rel}/pages/{stem}.pdf"
                text_rel = f"{section_rel}/text/{stem}.txt"
                analysis_rel = f"{section_rel}/analysis/{stem}.json"

                with fitz.open() as page_pdf:
                    page_pdf.insert_pdf(
                        section_pdf, from_page=page_number - 1, to_page=page_number - 1
                    )
                    page_pdf.save(document_dir / page_pdf_rel)

                source_page = source_doc[source_page_number - 1]
                page_text = source_page.get_text("text") or ""
                if not page_text.strip():
                    empty_text_pages += 1
                (document_dir / text_rel).write_text(page_text, encoding="utf-8")

                page_analysis = {
                    "archiveId": ids["archiveId"],
                    "archiveSlug": ids["archiveSlug"],
                    "submissionId": ids["submissionId"],
                    "submissionSlug": ids["submissionSlug"],
                    "documentId": ids["documentId"],
                    "documentSlug": ids["documentSlug"],
                    "sectionId": summary["sectionId"],
                    "sectionSlug": section.slug,
                    "sectionIndex": index,
                    "pageNumber": page_number,
                    "sourcePageNumber": source_page_number,
                    "pageLabel": source_page.get_label() or str(source_page_number),
                    "sourcePdf": page_pdf_rel,
                    "sourceText": text_rel,
                    "citation": {
                        "lowLevel": f"{ids['documentSlug']} p.{source_page_number}",
                        "display": (
                            f"{ids['submissionSlug']} / {ids['documentSlug']}"
                            f" p.{source_page_number}"
                        ),
                    },
                    **legal_analysis_placeholders(),
                    "confidence": None,
                    "needsReview": True,
                }
                if apply_preserved_analysis(
                    page_analysis, preservation_index, generated_at
                ):
                    preserved_count += 1
                write_json(document_dir / analysis_rel, page_analysis)

                toc_pages.append(
                    {
                        "pageNumber": page_number,
                        "sourcePageNumber": source_page_number,
                        "pdfPath": page_pdf_rel,
                        "textPath": text_rel,
                        "analysisPath": analysis_rel,
                        "sectionSlug": section.slug,
                        "sectionId": summary["sectionId"],
                        "title": "",
                    }
                )

        section_pdf_sha = sha256_file(document_dir / section_pdf_rel)
        ocr_likely_needed = (
            section.page_count > 0 and empty_text_pages == section.page_count
        )
        needs_review = (
            section.confidence < REVIEW_CONFIDENCE_THRESHOLD or ocr_likely_needed
        )

        section_meta = {
            "archiveId": ids["archiveId"],
            "archiveSlug": ids["archiveSlug"],
            "submissionId": ids["submissionId"],
            "submissionSlug": ids["submissionSlug"],
            "documentId": ids["documentId"],
            "documentSlug": ids["documentSlug"],
            "sectionId": summary["sectionId"],
            "sectionSlug": section.slug,
            "sectionIndex": index,
            "title": section.title,
            "sourceZipPath": ids["sourceZipPath"],
            "sourceDocumentFilename": ids["originalFilename"],
            "sourceDocumentSha256": ids["sha256"],
            "sourcePageStart": section.start_page,
            "sourcePageEnd": section.end_page,
            "sourcePageCount": section.page_count,
            "pageCount": section.page_count,
            "sectionPdfPath": section_pdf_rel,
            "sectionPdfSha256": section_pdf_sha,
            "boundaryConfidence": section.confidence,
            "boundaryReason": section.reason,
            "detectionTier": section.detection_tier,
            "documentFamily": section.document_family,
            "emptyTextPageCount": empty_text_pages,
            "ocrLikelyNeeded": ocr_likely_needed,
            "needsHumanReview": needs_review,
            "status": "exploded",
            "submissionType": "",
            "filingParty": "",
            "courtOrAgency": "",
            "caseNumber": "",
            "tags": [],
            "notes": "",
        }

        section_overlay = {
            **curation_defaults,
            **section_curation_for(
                document_curation, section.slug, summary["sectionId"], section.title
            ),
        }
        if apply_metadata_overlay(section_meta, section_overlay, ALLOWED_CURATED_FIELDS):
            curated_section_count += 1
        write_json(section_dir / "metadata.json", section_meta)

        # Curated review/classification fields surface in the enriched
        # records (document metadata + manifest) and the toc as well, so
        # navigation views agree with section metadata.
        surfaced_overlay_fields = {
            "submissionType",
            "filingParty",
            "courtOrAgency",
            "caseNumber",
            "tags",
            "notes",
            "needsHumanReview",
            "reviewNotes",
        }

        enriched_entry = {
            **summary,
            "path": section_rel,
            "metadataPath": f"{section_rel}/metadata.json",
            "sectionPdfPath": section_pdf_rel,
            "emptyTextPageCount": empty_text_pages,
            "ocrLikelyNeeded": ocr_likely_needed,
            "needsHumanReview": needs_review,
        }
        apply_metadata_overlay(enriched_entry, section_overlay, surfaced_overlay_fields)
        enriched.append(enriched_entry)

        toc_entry = {
            "sectionId": summary["sectionId"],
            "sectionSlug": section.slug,
            "sectionIndex": index,
            "title": section.title,
            "path": section_rel,
            "metadataPath": f"{section_rel}/metadata.json",
            "sectionPdfPath": section_pdf_rel,
            "sourcePageStart": section.start_page,
            "sourcePageEnd": section.end_page,
            "pageCount": section.page_count,
            "boundaryConfidence": section.confidence,
            "detectionTier": section.detection_tier,
            "needsHumanReview": needs_review,
            "pages": toc_pages,
        }
        apply_metadata_overlay(toc_entry, section_overlay, surfaced_overlay_fields)
        toc_sections.append(toc_entry)

    toc = {
        "archiveId": ids["archiveId"],
        "archiveSlug": ids["archiveSlug"],
        "submissionId": ids["submissionId"],
        "submissionSlug": ids["submissionSlug"],
        "documentId": ids["documentId"],
        "documentSlug": ids["documentSlug"],
        "title": ids["title"],
        "sourceZipPath": ids["sourceZipPath"],
        "originalFilename": ids["originalFilename"],
        "pageCount": source_doc.page_count,
        "sectionCount": len(sections),
        "sections": toc_sections,
    }
    write_json(document_dir / "toc.json", toc)

    return enriched, toc, {
        "reviewedAnalysisPreserved": preserved_count,
        "curatedSectionsApplied": curated_section_count,
    }


def manifest_section_entry(section: dict, document_base: str) -> dict:
    """Compact, text-free manifest summary of one exploded section. Accepts
    both pre-explosion summaries (startPage/endPage, no paths) and enriched
    ones (sourcePage* aliases come from section metadata naming)."""

    def corpus_path(rel: str) -> str:
        return f"{document_base}/{rel}" if rel else ""

    entry = {
        "sectionId": section.get("sectionId", ""),
        "sectionSlug": section.get("sectionSlug", ""),
        "sectionIndex": section.get("sectionIndex", 0),
        "title": section.get("title", ""),
        "metadataPath": corpus_path(section.get("metadataPath", "")),
        "sectionPdfPath": corpus_path(section.get("sectionPdfPath", "")),
        "sourcePageStart": section.get("sourcePageStart", section.get("startPage", 0)),
        "sourcePageEnd": section.get("sourcePageEnd", section.get("endPage", 0)),
        "pageCount": section.get("pageCount", 0),
        "boundaryConfidence": section.get(
            "boundaryConfidence", section.get("confidence", 0.0)
        ),
        "detectionTier": section.get("detectionTier", ""),
        "needsHumanReview": section.get("needsHumanReview", True),
    }
    # Surface curated classification fields when the enriched record has them.
    for key in ("submissionType", "filingParty", "tags"):
        if key in section:
            entry[key] = section[key]
    return entry


def document_manifest_entry(document_meta: dict, submission_slug: str) -> dict:
    document_slug = document_meta.get("documentSlug", "")
    base = f"submissions/{submission_slug}/documents/{document_slug}"
    return {
        "documentId": document_meta.get("documentId", ""),
        "documentSlug": document_slug,
        "title": document_meta.get("title", ""),
        "metadataPath": f"{base}/metadata.json",
        "sourcePdfPath": f"{base}/source.pdf",
        "sourceZipPath": document_meta.get("sourceZipPath", ""),
        "pageCount": document_meta.get("pageCount", 0),
        "sectionCount": document_meta.get("sectionCount", 0),
        "sections": [
            manifest_section_entry(s, base)
            for s in document_meta.get("sections", [])
        ],
    }


def submission_manifest_entry(submission_meta: dict, documents: list[dict]) -> dict:
    submission_slug = submission_meta.get("submissionSlug", "")
    return {
        "submissionId": submission_meta.get("submissionId", ""),
        "submissionSlug": submission_slug,
        "title": submission_meta.get("submissionTitle", ""),
        "metadataPath": f"submissions/{submission_slug}/metadata.json",
        "documentCount": len(documents),
        "pageCount": submission_meta.get("pageCount", 0),
        "documents": documents,
    }


def submission_entry_from_existing(submission_dir: Path) -> dict | None:
    """Rebuild a manifest entry for a skipped (already modeled) submission."""
    try:
        submission_meta = json.loads(
            (submission_dir / "metadata.json").read_text(encoding="utf-8")
        )
    except Exception:
        return None

    documents: list[dict] = []
    submission_slug = submission_meta.get("submissionSlug", submission_dir.name)

    for meta_path in sorted((submission_dir / "documents").glob("*/metadata.json")):
        try:
            document_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            console.print(
                f"[red]Warning:[/] could not read {meta_path}; document omitted from manifest"
            )
            continue
        documents.append(document_manifest_entry(document_meta, submission_slug))

    return submission_manifest_entry(submission_meta, documents)


def write_corpus(
    zip_path: Path,
    corpus_dir: Path,
    force: bool,
    manual_boundaries: dict,
    curation: dict | None = None,
    curation_path: Path | None = None,
) -> dict:
    """Write the Archive -> Submission -> Document corpus model and explode
    every document into section PDFs, page PDFs, page text, page analysis
    stubs, section metadata, and a document toc.json.

    Re-runs skip existing submission folders unless --force, which rebuilds
    them and overwrites all generated artifacts. Before --force deletes
    anything, reviewed page analysis (needsReview exactly false) is indexed
    via collect_reviewed_analysis() and re-applied onto the regenerated
    stubs; unreviewed stubs and invalid JSON are never preserved.

    The optional curation overlay (src/filings/corpus-curation.json) enriches
    submission/document/section metadata with allowed curated fields; the
    generated output remains fully regenerable from the committed sources.
    """
    curation = curation or {}
    curation_defaults = curation.get("defaults")
    if not isinstance(curation_defaults, dict):
        curation_defaults = {}
    curated_documents_applied = 0
    curated_sections_applied = 0

    report = inspect_archive(zip_path, manual_boundaries)

    archive_slug = slugify(zip_path.stem) or "archive"
    archive_id = f"arch_{report['zipSha256'][:16]}"
    generated_at = now_iso()
    total_pages = sum(e.page_count or 0 for e in report["pdfEntries"])

    corpus_dir.mkdir(parents=True, exist_ok=True)
    submissions_dir = corpus_dir / "submissions"
    submissions_dir.mkdir(exist_ok=True)

    # Index reviewed analysis before any submission folder is deleted.
    # Non-force runs never delete, so there is nothing to preserve.
    if force:
        preservation_index, preservation_stats = collect_reviewed_analysis(corpus_dir)
    else:
        preservation_index = {"exact": {}, "fallback": {}}
        preservation_stats = {
            "discovered": 0,
            "indexed": 0,
            "invalid": 0,
            "duplicates": 0,
            "unmatched": 0,
        }
    preserved_total = 0

    archive_meta = {
        "archiveId": archive_id,
        "archiveSlug": archive_slug,
        "archiveFilename": zip_path.name,
        "sourceArchivePath": str(zip_path),
        "archiveSha256": report["zipSha256"],
        "generatedAt": generated_at,
        "totalEntries": report["totalEntries"],
        "pdfCount": len(report["pdfEntries"]),
        "totalPageCount": total_pages,
        "nestedZipCount": len(report["nestedZips"]),
        "suspiciousEntryCount": len(report["suspiciousEntries"]),
    }
    (corpus_dir / "archive.json").write_text(
        json.dumps(archive_meta, indent=2), encoding="utf-8"
    )

    manifest: dict = {
        "version": 1,
        "generatedAt": generated_at,
        "archive": archive_meta,
        "submissions": [],
        "skipped": [],
    }

    for name in report["suspiciousEntries"]:
        console.print(f"[red]Suspicious entry not copied:[/] {name}")
        manifest["skipped"].append(
            {"sourceZipPath": name, "error": "suspicious path traversal entry; not copied"}
        )

    if report["nestedZips"]:
        console.print("[yellow]Nested ZIPs found (reported only, not expanded):[/]")
        for name in report["nestedZips"]:
            console.print(f"  - {name}")

    with zipfile.ZipFile(zip_path) as z:
        for entry in report["pdfEntries"]:
            if entry.page_count is None or entry.sha256 is None:
                console.print(
                    f"[red]Skipping unreadable PDF:[/] {entry.zip_path}: {entry.error}"
                )
                manifest["skipped"].append(
                    {"sourceZipPath": entry.zip_path, "error": entry.error}
                )
                continue

            submission_dir = submissions_dir / entry.submission_slug

            if submission_dir.exists() and not force:
                console.print(
                    f"[yellow]Skipping existing submission:[/] {entry.submission_slug}"
                )
                existing = submission_entry_from_existing(submission_dir)
                if existing is None:
                    console.print(
                        f"[red]Warning:[/] could not read metadata under"
                        f" {submission_dir}; manifest entry omitted"
                    )
                else:
                    manifest["submissions"].append(existing)
                continue

            if submission_dir.exists() and force:
                shutil.rmtree(submission_dir)

            document_dir = submission_dir / "documents" / entry.document_slug
            document_dir.mkdir(parents=True, exist_ok=True)

            # Copy by reading entry bytes and writing to a slug-derived path —
            # never extract using the zip entry's own name.
            source_bytes = z.read(entry.zip_path)
            (document_dir / "source.pdf").write_bytes(source_bytes)

            submission_id = f"sub_{entry.sha256[:16]}"
            document_id = f"doc_{entry.sha256[:16]}"
            title = Path(entry.zip_path).stem
            boundary_summaries = [
                section_summary(s, i, entry.sha256)
                for i, s in enumerate(entry.sections, start=1)
            ]

            ids = {
                "archiveId": archive_id,
                "archiveSlug": archive_slug,
                "submissionId": submission_id,
                "submissionSlug": entry.submission_slug,
                "documentId": document_id,
                "documentSlug": entry.document_slug,
                "title": title,
                "sourceZipPath": entry.zip_path,
                "originalFilename": entry.filename,
                "sha256": entry.sha256,
            }
            document_curation = document_curation_for(
                curation, entry.document_slug, entry.zip_path, entry.filename
            )
            document_overlay = {
                **curation_defaults,
                **{k: v for k, v in document_curation.items() if k != "sections"},
            }

            with fitz.open(stream=source_bytes, filetype="pdf") as source_doc:
                section_records, _toc, explode_stats = explode_document(
                    source_doc,
                    document_dir,
                    ids,
                    entry.sections,
                    boundary_summaries,
                    preservation_index,
                    generated_at,
                    document_curation,
                    curation_defaults,
                )
            preserved_total += explode_stats["reviewedAnalysisPreserved"]
            curated_sections_applied += explode_stats["curatedSectionsApplied"]
            sections_need_review = any(
                s["needsHumanReview"] for s in section_records
            )

            document_meta = {
                "archiveId": archive_id,
                "archiveSlug": archive_slug,
                "submissionId": submission_id,
                "submissionSlug": entry.submission_slug,
                "documentId": document_id,
                "documentSlug": entry.document_slug,
                "title": title,
                "originalFilename": entry.filename,
                "sourceZipPath": entry.zip_path,
                "sha256": entry.sha256,
                "pageCount": entry.page_count,
                "sourceType": "source-pdf",
                "status": "exploded",
                "sectionCount": len(entry.sections),
                "sections": section_records,
                "needsHumanReview": sections_need_review,
                "reviewNotes": "",
            }
            if apply_metadata_overlay(
                document_meta, document_overlay, ALLOWED_CURATED_FIELDS
            ):
                curated_documents_applied += 1
            write_json(document_dir / "metadata.json", document_meta)

            analysis = {
                "archiveId": archive_id,
                "archiveSlug": archive_slug,
                "submissionId": submission_id,
                "submissionSlug": entry.submission_slug,
                "documentId": document_id,
                "documentSlug": entry.document_slug,
                "sourceZipPath": entry.zip_path,
                "originalFilename": entry.filename,
                "detectedAt": generated_at,
                "detectedSections": boundary_summaries,
                "confidenceDistribution": confidence_distribution(entry.sections),
                "explodedAt": generated_at,
                "outputStatus": "exploded",
                "sectionCount": len(entry.sections),
                "pageCount": entry.page_count,
            }
            write_json(document_dir / "document-analysis.json", analysis)

            submission_meta = {
                "archiveId": archive_id,
                "archiveSlug": archive_slug,
                "submissionId": submission_id,
                "submissionSlug": entry.submission_slug,
                "submissionTitle": title,
                "submissionDate": "",
                "submissionType": "",
                "filingParty": "",
                "courtTransactionId": "",
                "efileEnvelopeId": "",
                "sourceZipPath": entry.zip_path,
                "documentCount": 1,
                "pageCount": entry.page_count,
                "needsHumanReview": True,
                "reviewNotes": "Default one-PDF submission; not yet human curated.",
                "status": "modeled",
            }
            apply_metadata_overlay(
                submission_meta, document_overlay, ALLOWED_CURATED_FIELDS
            )
            (submission_dir / "metadata.json").write_text(
                json.dumps(submission_meta, indent=2), encoding="utf-8"
            )

            manifest["submissions"].append(
                submission_manifest_entry(
                    submission_meta,
                    [document_manifest_entry(document_meta, entry.submission_slug)],
                )
            )

    manifest["reviewPreservation"] = {
        "reviewedAnalysisDiscovered": preservation_stats["discovered"],
        "reviewedAnalysisIndexed": preservation_stats["indexed"],
        "reviewedAnalysisPreserved": preserved_total,
        "reviewedAnalysisInvalid": preservation_stats["invalid"],
        "reviewedAnalysisDuplicates": preservation_stats["duplicates"],
        "reviewedAnalysisUnmatched": preservation_stats["unmatched"],
    }

    manifest["curation"] = {
        "loaded": bool(curation),
        "path": str(curation_path) if curation and curation_path else "",
        "documentsApplied": curated_documents_applied,
        "sectionsApplied": curated_sections_applied,
    }

    (corpus_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    return manifest
