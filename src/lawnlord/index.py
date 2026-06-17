"""Index the exploded corpus into DuckDB: ``documents`` + page ``chunks``.

Driven by the corpus ``manifest.json`` and each image's ``toc.json`` (the
authoritative page enumeration — never globs the filesystem). Each detected
boundary *section* on disk is a **document within the image**: this step inserts
one ``documents`` row per detected document and one ``chunks`` row per page,
links them to the already-ingested ``images`` row by image id (``doc_<sha16>``),
and cross-checks the exploder's actual page count against the declared
``filings.json`` ``pageCount`` (flagging mismatches, not trusting blindly).

(The on-disk corpus still names these boundaries "sections" — that exploder
vocabulary is mapped to ``documents`` here, at the index boundary.)

Determinism: row timestamps come from the corpus ``generatedAt``, so re-indexing
the same corpus is byte-identical. An integrity guard (run before any insert)
fails loudly if a page is dropped or duplicated; the whole re-index runs in one
transaction, so a failure rolls back and leaves the previous good index intact.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .dates import extract_dates
from .hashing import sha256_file
from .workspace import Case


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def index_corpus(
    con: duckdb.DuckDBPyConnection,
    case: Case,
    corpus_dir: str | Path | None = None,
    generated_at: str | None = None,
) -> dict:
    """Index the exploded corpus under ``corpus_dir`` (default: the case's
    corpus dir) into the documents/chunks tables. Returns row counts, any
    declared-vs-actual page-count mismatches, and the count of un-docketed
    images. Raises on a missing manifest or a broken page-coverage invariant
    (rolling back so the prior index survives)."""
    corpus_dir = Path(corpus_dir) if corpus_dir else case.corpus_dir
    manifest_path = corpus_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"corpus manifest not found: {manifest_path}")
    manifest = _load(manifest_path)
    generated_at = generated_at or manifest.get("generatedAt", "")
    case_id = case.identity.case_number or case.case_slug

    # One transaction: a guard failure rolls back the whole re-index, leaving
    # the previous good index intact rather than a half-written one.
    con.execute("BEGIN TRANSACTION")
    try:
        # Drop-and-rebuild this case's corpus rows (idempotent re-index).
        con.execute("DELETE FROM chunks WHERE case_id = ?", [case_id])
        con.execute("DELETE FROM documents WHERE case_id = ?", [case_id])
        con.execute("DELETE FROM extracted_dates WHERE case_id = ?", [case_id])
        stats = _index_documents(con, manifest, corpus_dir, case_id, generated_at)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    # Build the ranked full-text index over page text (outside the txn; a valid
    # chunk index already committed). Best-effort: if the FTS extension can't
    # load, search falls back to a substring scan.
    stats["fts"] = _build_fts_index(con)
    return stats


def _build_fts_index(con: duckdb.DuckDBPyConnection) -> bool:
    """(Re)build the BM25 full-text index over ``chunks.text``. Returns True if
    built. Non-fatal on failure — query falls back to LIKE."""
    from .db import load_fts

    if not load_fts(con):
        return False
    try:
        con.execute("PRAGMA create_fts_index('chunks', 'id', 'text', overwrite=1)")
        return True
    except Exception:
        return False


def _index_documents(
    con: duckdb.DuckDBPyConnection,
    manifest: dict,
    corpus_dir: Path,
    case_id: str,
    generated_at: str,
) -> dict:
    """Insert documents/chunks for every image in the manifest (inside the
    caller's transaction). Each on-disk boundary "section" becomes a document
    within its image. Raises ValueError on broken page coverage."""
    documents_n = 0
    chunks_n = 0
    dates_n = 0
    images_indexed = 0
    orphan_images = 0
    mismatches: list[dict] = []

    for submission in manifest.get("submissions", []):
        for image in submission.get("documents", []):
            image_id = image["documentId"]
            doc_dir = (corpus_dir / image["metadataPath"]).parent
            toc = _load(doc_dir / "toc.json")
            actual_pages = toc.get("pageCount", 0)
            toc_documents = toc.get("sections", [])

            # Integrity guard runs BEFORE any insert: a corrupt corpus fails
            # with a clear error (not a cryptic PK collision) and writes nothing.
            seen_pages = [
                pg["sourcePageNumber"]
                for doc in toc_documents
                for pg in doc.get("pages", [])
            ]
            document_page_sum = sum(doc.get("pageCount", 0) for doc in toc_documents)
            if sorted(seen_pages) != list(range(1, actual_pages + 1)):
                raise ValueError(
                    f"page coverage broken for {image_id}: "
                    f"{sorted(seen_pages)} != 1..{actual_pages}"
                )
            if document_page_sum != actual_pages:
                raise ValueError(
                    f"document page sum {document_page_sum} != actual "
                    f"{actual_pages} for {image_id}"
                )

            # Cross-check declared (filings.json) vs actual (exploder) page count.
            row = con.execute(
                "SELECT declared_page_count FROM images WHERE id = ?",
                [image_id],
            ).fetchone()
            if row is None:
                # In the corpus but not docketed in filings.json — index its
                # pages but surface it rather than silently creating orphans.
                orphan_images += 1
            else:
                declared = row[0]
                mismatch = declared is not None and declared != actual_pages
                con.execute(
                    "UPDATE images SET actual_page_count = ?, "
                    "page_count_mismatch = ? WHERE id = ?",
                    [actual_pages, mismatch, image_id],
                )
                if mismatch:
                    mismatches.append(
                        {"image_id": image_id, "declared": declared,
                         "actual": actual_pages}
                    )
            images_indexed += 1

            for doc in toc_documents:
                document_id = doc["sectionId"]
                # documentFamily is a secondary detection signal in the document
                # metadata (not in the toc); read it when present.
                doc_meta = (
                    _load(doc_dir / doc["metadataPath"])
                    if doc.get("metadataPath")
                    else {}
                )
                con.execute(
                    """
                    INSERT INTO documents (id, case_id, image_id, document_slug,
                        document_index, title, source_page_start, source_page_end,
                        page_count, boundary_confidence, detection_tier,
                        document_family, needs_review, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        document_id, case_id, image_id, doc.get("sectionSlug"),
                        doc.get("sectionIndex"), doc.get("title"),
                        doc.get("sourcePageStart"), doc.get("sourcePageEnd"),
                        doc.get("pageCount"), doc.get("boundaryConfidence"),
                        doc.get("detectionTier"), doc_meta.get("documentFamily", ""),
                        bool(doc.get("needsHumanReview")), generated_at,
                    ],
                )
                documents_n += 1

                for page in doc.get("pages", []):
                    spn = page["sourcePageNumber"]
                    text_path = doc_dir / page["textPath"]
                    text = (
                        text_path.read_text(encoding="utf-8")
                        if text_path.exists()
                        else ""
                    )
                    citation_low = citation_display = ""
                    text_source = None
                    ocr_confidence = None
                    analysis_path = doc_dir / page["analysisPath"]
                    if analysis_path.exists():
                        analysis = _load(analysis_path)
                        citation = analysis.get("citation", {}) or {}
                        citation_low = citation.get("lowLevel", "")
                        citation_display = citation.get("display", "")
                        text_source = analysis.get("textSource")
                        ocr_confidence = analysis.get("ocrConfidence")
                    # Pointer to the preserved page image (the per-page PDF), so a
                    # page is reconstructable from the data alone (#31). Path is
                    # corpus-relative; the sha256 pins the bytes on disk.
                    page_pdf = doc_dir / page["pdfPath"]
                    page_image_path = (
                        str(page_pdf.relative_to(corpus_dir)) if page_pdf.exists() else None
                    )
                    page_image_sha256 = sha256_file(page_pdf) if page_pdf.exists() else None
                    con.execute(
                        """
                        INSERT INTO chunks (id, case_id, image_id, document_id,
                            text, page_number, source_page_number, paragraph_number,
                            text_span_start, text_span_end, extraction_method,
                            citation_low, citation_display, confidence,
                            text_source, ocr_confidence, page_image_path,
                            page_image_sha256, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, NULL,
                            ?, ?, ?, ?, ?)
                        """,
                        [
                            f"{document_id}_p{spn}", case_id, image_id, document_id,
                            text, page.get("pageNumber"), spn, "pdf_text",
                            citation_low, citation_display,
                            text_source, ocr_confidence, page_image_path,
                            page_image_sha256, generated_at,
                        ],
                    )
                    chunks_n += 1

                    # Date-bearing facts on this page (#36). Facts, not
                    # interpretations: every row is flagged needs_review.
                    for di, fact in enumerate(extract_dates(text), start=1):
                        con.execute(
                            """
                            INSERT INTO extracted_dates (id, case_id, image_id,
                                document_id, source_page_number, date, raw_text,
                                snippet, text_span_start, text_span_end,
                                confidence, source, needs_review, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted', TRUE, ?)
                            """,
                            [
                                f"{document_id}_p{spn}_d{di}", case_id, image_id,
                                document_id, spn, fact["date"], fact["raw"],
                                fact["snippet"], fact["spanStart"], fact["spanEnd"],
                                fact["confidence"], generated_at,
                            ],
                        )
                        dates_n += 1

    return {
        "documents": documents_n,
        "chunks": chunks_n,
        "dates": dates_n,
        "images_indexed": images_indexed,
        "orphan_images": orphan_images,
        "mismatches": mismatches,
    }
