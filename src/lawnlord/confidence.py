"""Two-sided confidence (#33).

Score each page against **both** intake sources — the Odyssey metadata (does the
declared page count match the actual, and is the image docketed?) and the source
PDF (did text extract from the page?) — then roll the page scores up to documents
and the case. A page that clears the threshold is flagged ``ai_accessible``;
anything short is ``needs_review``. This is the readiness gate that decides what
legal analysis may build on; it never asserts a legal conclusion.
"""

from __future__ import annotations

import duckdb

THRESHOLD = 0.8


def score_case(con: duckdb.DuckDBPyConnection, case_id: str) -> dict:
    """Score and persist page/document/case confidence for ``case_id``.

    Each page scores half for **structure** (declared page count matches actual
    *and* the image is docketed — metadata vs. source) and half for **text
    fidelity** (the page extracted text — the source PDF). Returns a summary.
    """
    pages = con.execute(
        """
        SELECT c.id,
               (c.text IS NOT NULL AND length(trim(c.text)) > 0) AS has_text,
               COALESCE(i.page_count_mismatch, TRUE) AS mismatch,
               EXISTS (SELECT 1 FROM image_events ie WHERE ie.image_id = i.id) AS docketed
        FROM chunks c JOIN images i ON i.id = c.image_id
        WHERE c.case_id = ?
        """,
        [case_id],
    ).fetchall()
    ai_n = 0
    for chunk_id, has_text, mismatch, docketed in pages:
        structure = 0.5 if (not mismatch and docketed) else 0.0
        text = 0.5 if has_text else 0.0
        conf = round(structure + text, 4)
        ai = conf >= THRESHOLD
        con.execute(
            "UPDATE chunks SET confidence = ?, ai_accessible = ?, needs_review = ? WHERE id = ?",
            [conf, ai, not ai, chunk_id],
        )
        ai_n += 1 if ai else 0
    # Roll the page scores up to documents and the case (mean of their pages).
    con.execute(
        """
        UPDATE documents SET confidence = (
            SELECT avg(confidence) FROM chunks WHERE chunks.document_id = documents.id
        ) WHERE case_id = ?
        """,
        [case_id],
    )
    con.execute(
        """
        UPDATE cases SET confidence = (
            SELECT avg(confidence) FROM chunks WHERE chunks.case_id = cases.id
        ) WHERE id = ?
        """,
        [case_id],
    )
    row = con.execute("SELECT confidence FROM cases WHERE id = ?", [case_id]).fetchone()
    return {
        "scored_pages": len(pages),
        "ai_accessible": ai_n,
        "review_pages": len(pages) - ai_n,
        "case_confidence": row[0] if row else None,
    }
