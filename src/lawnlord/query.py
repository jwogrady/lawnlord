"""Read-only search over the case index, with provenance.

Every result carries enough to cite back to the record — the image (filed PDF)
title, the source page number, and the citation string — so an answer can always
be traced to a page. Pure SELECTs (parameterized); nothing here writes. Results
are ordered deterministically.

Vocabulary (see :mod:`lawnlord.db`): ``images`` are filed PDFs, ``documents`` are
the logical documents within an image, and ``chunks`` are pages.
"""

from __future__ import annotations

import duckdb


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict]:
    cur = con.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def search_text(con: duckdb.DuckDBPyConnection, text: str, limit: int = 50) -> list[dict]:
    """Pages whose extracted text contains ``text`` (case-insensitive), each
    with its image title, source page, and citation."""
    return _rows(
        con,
        """
        SELECT c.image_id, i.title AS image_title, c.source_page_number,
               c.citation_display, c.text
        FROM chunks c
        LEFT JOIN images i ON i.id = c.image_id
        WHERE lower(c.text) LIKE ?
        ORDER BY c.image_id, c.source_page_number
        LIMIT ?
        """,
        ["%" + text.lower() + "%", limit],
    )


def needs_review_documents(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Documents-within-images flagged for human review (low boundary
    confidence or OCR likely needed), with their page range and why."""
    return _rows(
        con,
        """
        SELECT d.image_id, i.title AS image_title, d.document_slug,
               d.source_page_start, d.source_page_end, d.detection_tier,
               d.boundary_confidence
        FROM documents d
        LEFT JOIN images i ON i.id = d.image_id
        WHERE d.needs_review = TRUE
        ORDER BY d.image_id, d.document_index
        """,
        [],
    )


def images_by_phase(con: duckdb.DuckDBPyConnection, phase: str) -> list[dict]:
    """Images (filed PDFs) filed in a docket ``phase`` (e.g. "Summary Judgment")."""
    return _rows(
        con,
        """
        SELECT DISTINCT i.id AS image_id, i.title AS image_title,
               i.filing_date, i.docket_type
        FROM images i
        JOIN image_events ie ON ie.image_id = i.id
        JOIN events e ON e.id = ie.event_id
        WHERE e.phase = ?
        ORDER BY i.id
        """,
        [phase],
    )


def images_by_event(con: duckdb.DuckDBPyConnection, event_type: str) -> list[dict]:
    """Images tied to a docket event whose type contains ``event_type``."""
    return _rows(
        con,
        """
        SELECT DISTINCT i.id AS image_id, i.title AS image_title,
               i.filing_date, e.event_type
        FROM images i
        JOIN image_events ie ON ie.image_id = i.id
        JOIN events e ON e.id = ie.event_id
        WHERE lower(e.event_type) LIKE ?
        ORDER BY i.id
        """,
        ["%" + event_type.lower() + "%"],
    )


def images_by_party(con: duckdb.DuckDBPyConnection, party: str) -> list[dict]:
    """Images tied to docket events naming ``party``."""
    return _rows(
        con,
        """
        SELECT DISTINCT i.id AS image_id, i.title AS image_title,
               i.filing_date, e.party
        FROM images i
        JOIN image_events ie ON ie.image_id = i.id
        JOIN events e ON e.id = ie.event_id
        WHERE lower(e.party) LIKE ?
        ORDER BY i.id
        """,
        ["%" + party.lower() + "%"],
    )
