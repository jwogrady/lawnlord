"""Read-only search over the case index, with provenance.

Every result carries enough to cite back to the record — the image (filed PDF)
title, the source page number, and the citation string — so an answer can always
be traced to a page. Pure SELECTs (parameterized); nothing here writes. Results
are ordered deterministically.

Vocabulary (see :mod:`lawnlord.db`): ``images`` are filed PDFs, ``documents`` are
the logical documents within an image, and ``chunks`` are pages.
"""

from __future__ import annotations

import re

import duckdb


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict]:
    cur = con.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


_BM25_SQL = """
    SELECT c.image_id, i.title AS image_title, c.source_page_number,
           c.citation_display, c.text,
           fts_main_chunks.match_bm25(c.id, ?) AS score
    FROM chunks c
    LEFT JOIN images i ON i.id = c.image_id
    WHERE score IS NOT NULL
    ORDER BY score DESC, c.image_id, c.source_page_number
    LIMIT ?
"""

_LIKE_SQL = """
    SELECT c.image_id, i.title AS image_title, c.source_page_number,
           c.citation_display, c.text
    FROM chunks c
    LEFT JOIN images i ON i.id = c.image_id
    WHERE lower(c.text) LIKE ?
    ORDER BY c.image_id, c.source_page_number
    LIMIT ?
"""


def search_text(con: duckdb.DuckDBPyConnection, text: str, limit: int = 50) -> list[dict]:
    """Pages matching ``text``, each with its image title, source page, and
    citation. Uses the ranked BM25 full-text index (relevance-ordered, multi-term
    and phrase aware) when the FTS extension and index are available; otherwise
    falls back to a case-insensitive substring scan so search always works."""
    from .db import load_fts

    if load_fts(con):
        try:
            return _rows(con, _BM25_SQL, [text, limit])
        except Exception:
            pass  # no FTS index on this DB — fall back to substring
    return _rows(con, _LIKE_SQL, ["%" + text.lower() + "%", limit])


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


_DEADLINE_RE = re.compile(
    r"\b(deadline|due|expire\w*|respond|response|answer|hearing|trial|sale|"
    r"foreclosure|redemption|notice)\b",
    re.IGNORECASE,
)


def _looks_like_deadline(text: str) -> bool:
    return bool(_DEADLINE_RE.search(text or ""))


def timeline(con: duckdb.DuckDBPyConnection) -> dict:
    """The factual case timeline, derived only from the record: docket events
    and the date-bearing facts extracted from page text (#36). Read-only.

    Returns ``{"dated": [...], "undated": [...]}``. Each item carries its
    ``date`` (ISO), ``source`` ("docket" or "extracted"), a ``label``, a
    provenance ``detail``, and a ``flag`` set when the text *looks like* a
    deadline / hearing / sale — surfaced for review, not interpreted (deciding
    what a date means is the human's job). Nothing is hand-entered or invented;
    undated docket events are listed separately, never given a guessed date.
    """
    items: list[dict] = []
    for e in _rows(
        con, "SELECT date, phase, event_type, description, party FROM events", []
    ):
        label = e.get("event_type") or e.get("description") or ""
        items.append(
            {
                "date": e.get("date") or "",
                "source": "docket",
                "label": label,
                "detail": e.get("phase") or e.get("party") or "",
                "flag": _looks_like_deadline(f"{label} {e.get('description') or ''}"),
            }
        )
    for d in _rows(
        con,
        "SELECT date, snippet, image_id, source_page_number FROM extracted_dates",
        [],
    ):
        snippet = d.get("snippet") or ""
        items.append(
            {
                "date": d.get("date") or "",
                "source": "extracted",
                "label": snippet,
                "detail": f"{d.get('image_id')} p.{d.get('source_page_number')}",
                "flag": _looks_like_deadline(snippet),
            }
        )
    dated = sorted(
        (i for i in items if i["date"]),
        key=lambda i: (i["date"], i["source"], i["label"]),
    )
    undated = sorted(
        (i for i in items if not i["date"]), key=lambda i: (i["source"], i["label"])
    )
    return {"dated": dated, "undated": undated}
