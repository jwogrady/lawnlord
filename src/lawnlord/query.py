"""Read-only search over the case index, with provenance.

Every result carries enough to cite back to the record — document title, the
source page number, and the citation string — so an answer can always be traced
to a page. Pure SELECTs (parameterized); nothing here writes. Results are
ordered deterministically.
"""

from __future__ import annotations

import duckdb


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict]:
    cur = con.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def search_text(con: duckdb.DuckDBPyConnection, text: str, limit: int = 50) -> list[dict]:
    """Pages whose extracted text contains ``text`` (case-insensitive), each
    with its document title, source page, and citation."""
    return _rows(
        con,
        """
        SELECT c.document_id, d.title AS document_title, c.source_page_number,
               c.citation_display, c.text
        FROM chunks c
        LEFT JOIN documents d ON d.id = c.document_id
        WHERE lower(c.text) LIKE ?
        ORDER BY c.document_id, c.source_page_number
        LIMIT ?
        """,
        ["%" + text.lower() + "%", limit],
    )


def needs_review_sections(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Sections flagged for human review (low boundary confidence or OCR
    likely needed), with their page range and why."""
    return _rows(
        con,
        """
        SELECT s.document_id, d.title AS document_title, s.section_slug,
               s.source_page_start, s.source_page_end, s.detection_tier,
               s.boundary_confidence
        FROM sections s
        LEFT JOIN documents d ON d.id = s.document_id
        WHERE s.needs_review = TRUE
        ORDER BY s.document_id, s.section_index
        """,
        [],
    )


def documents_by_phase(con: duckdb.DuckDBPyConnection, phase: str) -> list[dict]:
    """Documents filed in a docket ``phase`` (e.g. "Summary Judgment")."""
    return _rows(
        con,
        """
        SELECT DISTINCT d.id AS document_id, d.title AS document_title,
               d.filing_date, d.docket_type
        FROM documents d
        JOIN document_events de ON de.document_id = d.id
        JOIN events e ON e.id = de.event_id
        WHERE e.phase = ?
        ORDER BY d.id
        """,
        [phase],
    )


def documents_by_event(con: duckdb.DuckDBPyConnection, event_type: str) -> list[dict]:
    """Documents tied to a docket event whose type contains ``event_type``."""
    return _rows(
        con,
        """
        SELECT DISTINCT d.id AS document_id, d.title AS document_title,
               d.filing_date, e.event_type
        FROM documents d
        JOIN document_events de ON de.document_id = d.id
        JOIN events e ON e.id = de.event_id
        WHERE lower(e.event_type) LIKE ?
        ORDER BY d.id
        """,
        ["%" + event_type.lower() + "%"],
    )


def documents_by_party(con: duckdb.DuckDBPyConnection, party: str) -> list[dict]:
    """Documents tied to docket events naming ``party``."""
    return _rows(
        con,
        """
        SELECT DISTINCT d.id AS document_id, d.title AS document_title,
               d.filing_date, e.party
        FROM documents d
        JOIN document_events de ON de.document_id = d.id
        JOIN events e ON e.id = de.event_id
        WHERE lower(e.party) LIKE ?
        ORDER BY d.id
        """,
        ["%" + party.lower() + "%"],
    )
