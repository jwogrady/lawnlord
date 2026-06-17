"""Index the exploded corpus into DuckDB: ``sections`` + page ``chunks``.

Driven by the corpus ``manifest.json`` and each document's ``toc.json`` (the
authoritative page enumeration — never globs the filesystem). Inserts one
``sections`` row per detected section and one ``chunks`` row per page, links them
to the already-ingested ``documents`` row by ``documentId`` (``doc_<sha16>``),
and cross-checks the exploder's actual page count against the declared
``filings.json`` ``pageCount`` (flagging mismatches, not trusting blindly).

Determinism: row timestamps come from the corpus ``generatedAt``, so re-indexing
the same corpus is byte-identical. An integrity guard (run before any insert)
fails loudly if a page is dropped or duplicated; the whole re-index runs in one
transaction, so a failure rolls back and leaves the previous good index intact.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

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
    corpus dir) into the sections/chunks tables. Returns row counts, any
    declared-vs-actual page-count mismatches, and the count of un-docketed
    documents. Raises on a missing manifest or a broken page-coverage invariant
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
        con.execute("DELETE FROM sections WHERE case_id = ?", [case_id])
        stats = _index_documents(con, manifest, corpus_dir, case_id, generated_at)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return stats


def _index_documents(
    con: duckdb.DuckDBPyConnection,
    manifest: dict,
    corpus_dir: Path,
    case_id: str,
    generated_at: str,
) -> dict:
    """Insert sections/chunks for every document in the manifest (inside the
    caller's transaction). Raises ValueError on broken page coverage."""
    sections_n = 0
    chunks_n = 0
    docs_indexed = 0
    orphan_documents = 0
    mismatches: list[dict] = []

    for submission in manifest.get("submissions", []):
        for doc in submission.get("documents", []):
            document_id = doc["documentId"]
            doc_dir = (corpus_dir / doc["metadataPath"]).parent
            toc = _load(doc_dir / "toc.json")
            actual_pages = toc.get("pageCount", 0)
            toc_sections = toc.get("sections", [])

            # Integrity guard runs BEFORE any insert: a corrupt corpus fails
            # with a clear error (not a cryptic PK collision) and writes nothing.
            seen_pages = [
                pg["sourcePageNumber"]
                for sec in toc_sections
                for pg in sec.get("pages", [])
            ]
            section_page_sum = sum(sec.get("pageCount", 0) for sec in toc_sections)
            if sorted(seen_pages) != list(range(1, actual_pages + 1)):
                raise ValueError(
                    f"page coverage broken for {document_id}: "
                    f"{sorted(seen_pages)} != 1..{actual_pages}"
                )
            if section_page_sum != actual_pages:
                raise ValueError(
                    f"section page sum {section_page_sum} != actual "
                    f"{actual_pages} for {document_id}"
                )

            # Cross-check declared (filings.json) vs actual (exploder) page count.
            row = con.execute(
                "SELECT declared_page_count FROM documents WHERE id = ?",
                [document_id],
            ).fetchone()
            if row is None:
                # In the corpus but not docketed in filings.json — index its
                # pages but surface it rather than silently creating orphans.
                orphan_documents += 1
            else:
                declared = row[0]
                mismatch = declared is not None and declared != actual_pages
                con.execute(
                    "UPDATE documents SET actual_page_count = ?, "
                    "page_count_mismatch = ? WHERE id = ?",
                    [actual_pages, mismatch, document_id],
                )
                if mismatch:
                    mismatches.append(
                        {"document_id": document_id, "declared": declared,
                         "actual": actual_pages}
                    )
            docs_indexed += 1

            for sec in toc_sections:
                section_id = sec["sectionId"]
                # documentFamily is a secondary detection signal in the section
                # metadata (not in the toc); read it when present.
                sec_meta = (
                    _load(doc_dir / sec["metadataPath"])
                    if sec.get("metadataPath")
                    else {}
                )
                con.execute(
                    """
                    INSERT INTO sections (id, case_id, document_id, section_slug,
                        section_index, title, source_page_start, source_page_end,
                        page_count, boundary_confidence, detection_tier,
                        document_family, needs_review, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        section_id, case_id, document_id, sec.get("sectionSlug"),
                        sec.get("sectionIndex"), sec.get("title"),
                        sec.get("sourcePageStart"), sec.get("sourcePageEnd"),
                        sec.get("pageCount"), sec.get("boundaryConfidence"),
                        sec.get("detectionTier"), sec_meta.get("documentFamily", ""),
                        bool(sec.get("needsHumanReview")), generated_at,
                    ],
                )
                sections_n += 1

                for page in sec.get("pages", []):
                    spn = page["sourcePageNumber"]
                    text_path = doc_dir / page["textPath"]
                    text = (
                        text_path.read_text(encoding="utf-8")
                        if text_path.exists()
                        else ""
                    )
                    citation_low = citation_display = ""
                    analysis_path = doc_dir / page["analysisPath"]
                    if analysis_path.exists():
                        citation = _load(analysis_path).get("citation", {}) or {}
                        citation_low = citation.get("lowLevel", "")
                        citation_display = citation.get("display", "")
                    con.execute(
                        """
                        INSERT INTO chunks (id, case_id, document_id, section_id,
                            text, page_number, source_page_number, paragraph_number,
                            text_span_start, text_span_end, extraction_method,
                            citation_low, citation_display, confidence, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, NULL, ?)
                        """,
                        [
                            f"{section_id}_p{spn}", case_id, document_id, section_id,
                            text, page.get("pageNumber"), spn, "pdf_text",
                            citation_low, citation_display, generated_at,
                        ],
                    )
                    chunks_n += 1

    return {
        "sections": sections_n,
        "chunks": chunks_n,
        "documents_indexed": docs_indexed,
        "orphan_documents": orphan_documents,
        "mismatches": mismatches,
    }
