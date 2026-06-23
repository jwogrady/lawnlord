"""Read the Actual-lens view out of a case's DuckDB mirror.

The Actual lens reproduces the Odyssey portal from the **mirror** (the seven
tables :mod:`lawnlord.ingest` populates) — never by re-parsing the zip. This
module is read-only: one query set → a JSON-able dict the viewer consumes (case
header, parties, the register of actions with each entry's filed documents, and
the document set). It ends at the image, like Odyssey.
"""

from __future__ import annotations

import duckdb


def _one(con: duckdb.DuckDBPyConnection, sql: str) -> dict:
    cur = con.execute(sql)
    row = cur.fetchone()
    if row is None:
        return {}
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def export_actual(con: duckdb.DuckDBPyConnection) -> dict:
    """Build the Actual-lens payload from the mirror tables (read-only)."""
    case = _one(
        con,
        "SELECT id AS number, title, court, case_type AS caseType, status, "
        "date_filed AS dateFiled, judicial_officer AS judicialOfficer "
        "FROM cases LIMIT 1",
    )

    parties = _rows(
        con,
        "SELECT role, name, representation, location FROM parties "
        "ORDER BY role, name",
    )

    documents = _rows(
        con,
        "SELECT title, filename, intake_path AS intakePath, "
        "declared_page_count AS declaredPageCount, filing_date AS filingDate, "
        "docket_type AS docketEvent FROM images ORDER BY filing_date, title",
    )

    # The register of actions: every event, in docket order, with the filed
    # documents (images) linked to it via image_events.
    events = _rows(
        con,
        "SELECT id, date, event_type AS event, party, phase AS section "
        "FROM events ORDER BY date, id",
    )
    docs_for: dict[str, list[dict]] = {}
    for link in _rows(
        con,
        "SELECT ie.event_id AS event_id, i.title, i.filename, "
        "i.intake_path AS intakePath, i.declared_page_count AS declaredPageCount "
        "FROM image_events ie JOIN images i ON i.id = ie.image_id",
    ):
        docs_for.setdefault(link.pop("event_id"), []).append(link)
    register = []
    for e in events:
        eid = e.pop("id")
        e["documents"] = docs_for.get(eid, [])
        register.append(e)

    return {
        "case": case,
        "parties": parties,
        "registerOfActions": register,
        "documents": documents,
    }


def export_exploded(con: duckdb.DuckDBPyConnection) -> dict:
    """Build the Exploded-lens payload: each image → its documents → pages, with
    the latest transcription beside each page. Read-only.

    Each page carries its transcription ``source`` (``'pdf_text'`` = exact text
    from the PDF's own layer, ``'ai'`` = a vision model's reading), ``model``, and
    ``fidelity`` — so a reader can tell extracted ground truth from a model's
    reading of pixels. Pages whose transcription hasn't been run carry
    ``text: null`` (the lens still shows the page image). The latest revision per
    page wins.
    """
    # Latest transcription per page (max rev), if any.
    text_by_page: dict[str, dict] = {}
    for r in _rows(
        con,
        "SELECT pt.page_id, pt.text, pt.source, pt.model, pt.fidelity FROM page_text pt "
        "JOIN (SELECT page_id, max(rev) AS rev FROM page_text GROUP BY page_id) m "
        "ON m.page_id = pt.page_id AND m.rev = pt.rev",
    ):
        text_by_page[r["page_id"]] = {
            "text": r["text"], "source": r["source"],
            "model": r["model"], "fidelity": r["fidelity"],
        }

    pages_by_doc: dict[str, list[dict]] = {}
    for p in _rows(
        con,
        "SELECT id, document_id, page_number AS pageNumber, "
        "page_image_path AS png FROM pages ORDER BY document_id, page_number",
    ):
        t = text_by_page.get(p.pop("id"), {})
        p["text"] = t.get("text")
        p["source"] = t.get("source")
        p["model"] = t.get("model")
        p["fidelity"] = t.get("fidelity")
        pages_by_doc.setdefault(p.pop("document_id"), []).append(p)

    docs_by_image: dict[str, list[dict]] = {}
    for d in _rows(
        con,
        "SELECT id, image_id, title, page_count AS pageCount FROM documents "
        "ORDER BY image_id, id",
    ):
        d["pages"] = pages_by_doc.get(d.pop("id"), [])
        docs_by_image.setdefault(d.pop("image_id"), []).append(d)

    images = _rows(
        con,
        "SELECT id AS imageId, title, filename FROM images ORDER BY filing_date, title",
    )
    for img in images:
        img["documents"] = docs_by_image.get(img["imageId"], [])

    return {"images": images}
