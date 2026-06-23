"""Read the case views out of a case's DuckDB mirror.

Two lenses, both read-only — one query set → a JSON-able dict the viewer
consumes, never by re-parsing the zip:

- The **Actual lens** (:func:`export_actual`) reproduces the Odyssey portal from
  the **mirror** (the seven tables :mod:`lawnlord.ingest` populates): case header,
  parties, the register of actions with each entry's filed documents, and the
  document set. It ends at the image, like Odyssey.
- The **Exploded lens** (:func:`export_exploded`) goes inside each PDF:
  case → image → document → page, each page carrying *every* transcription
  variation beside it.

The Exploded lens is **addressable at every hierarchy level** (ADR-0007) — the
whole case, or a single filing, image, document, or page — each a pure function
of the connection returning the same nested shape scoped to that node. A
**filing** is a grouping, not a tree node: filings↔images are many-to-many via
``image_events``, so a filing-level export returns the images linked to that
event (overlap with other filings allowed). This module never writes.
"""

from __future__ import annotations

import duckdb


def _one(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> dict:
    cur = con.execute(sql, params or [])
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


# --- Exploded lens: case → image → document → page → transcriptions ---------
#
# A page's transcriptions are *every current variation* — the latest rev per
# (page_id, source, model). pdf_text has a null model, so match nulls with
# IS NOT DISTINCT FROM. Ordered ground-truth first (pdf_text), then ai by model.

_VARIATIONS_SQL = """
SELECT pt.page_id, pt.source, pt.model, pt.rev, pt.fidelity, pt.text,
       pt.created_at AS createdAt
FROM page_text pt
JOIN (SELECT page_id, source, model, max(rev) AS rev FROM page_text
      GROUP BY page_id, source, model) m
ON m.page_id = pt.page_id AND m.source = pt.source
 AND m.model IS NOT DISTINCT FROM pt.model AND m.rev = pt.rev
"""


def _variations_by_page(
    con: duckdb.DuckDBPyConnection, where: str = "", params: list | None = None
) -> dict[str, list[dict]]:
    """Map page_id → its current transcription variations (latest rev per
    ``(page_id, source, model)``), each sorted ground-truth-first."""
    sql = _VARIATIONS_SQL
    if where:
        sql += f" AND pt.page_id IN ({where})"
    by_page: dict[str, list[dict]] = {}
    for r in _rows(con, sql, params):
        entry = {
            "source": r["source"],
            "model": r["model"],
            "rev": r["rev"],
            "createdAt": r["createdAt"],
            "fidelity": r["fidelity"],
            "text": r["text"],
        }
        by_page.setdefault(r["page_id"], []).append(entry)
    for entries in by_page.values():
        entries.sort(key=lambda t: (t["source"] != "pdf_text", t["source"], t["model"] or ""))
    return by_page


def _pages(
    con: duckdb.DuckDBPyConnection, where: str = "", params: list | None = None
) -> list[dict]:
    """Pages (optionally scoped by a WHERE clause), each with its
    ``transcriptions`` list."""
    sql = (
        "SELECT id, document_id, page_number AS pageNumber, "
        "page_image_path AS png FROM pages"
    )
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY document_id, page_number"
    rows = _rows(con, sql, params)
    if not rows:
        return []
    page_ids = [r["id"] for r in rows]
    placeholders = ", ".join("?" for _ in page_ids)
    vars_by_page = _variations_by_page(con, placeholders, page_ids)
    for p in rows:
        p["transcriptions"] = vars_by_page.get(p["id"], [])
    return rows


def export_page(con: duckdb.DuckDBPyConnection, page_id: str) -> dict:
    """A single page scoped to ``page_id``, with its ``transcriptions`` list."""
    pages = _pages(con, "id = ?", [page_id])
    if not pages:
        return {}
    page = pages[0]
    page.pop("document_id", None)
    return {"page": page}


def _documents_for(
    con: duckdb.DuckDBPyConnection, where: str = "", params: list | None = None
) -> list[dict]:
    """Documents (optionally scoped) with their pages + transcriptions nested."""
    sql = (
        "SELECT id, image_id, title, page_count AS pageCount FROM documents"
    )
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY image_id, id"
    docs = _rows(con, sql, params)
    if not docs:
        return []
    doc_ids = [d["id"] for d in docs]
    placeholders = ", ".join("?" for _ in doc_ids)
    pages_by_doc: dict[str, list[dict]] = {}
    for p in _pages(con, f"document_id IN ({placeholders})", doc_ids):
        pages_by_doc.setdefault(p.pop("document_id"), []).append(p)
    for d in docs:
        d["pages"] = pages_by_doc.get(d["id"], [])
    return docs


def export_document(con: duckdb.DuckDBPyConnection, document_id: str) -> dict:
    """A single document scoped to ``document_id``, with its pages nested."""
    docs = _documents_for(con, "id = ?", [document_id])
    if not docs:
        return {}
    doc = docs[0]
    doc.pop("image_id", None)
    return {"document": doc}


def _images_for(
    con: duckdb.DuckDBPyConnection, where: str = "", params: list | None = None
) -> list[dict]:
    """Images (optionally scoped) with their documents → pages nested."""
    sql = "SELECT id AS imageId, title, filename FROM images"
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY filing_date, title"
    images = _rows(con, sql, params)
    if not images:
        return []
    image_ids = [img["imageId"] for img in images]
    placeholders = ", ".join("?" for _ in image_ids)
    docs_by_image: dict[str, list[dict]] = {}
    for d in _documents_for(con, f"image_id IN ({placeholders})", image_ids):
        docs_by_image.setdefault(d.pop("image_id"), []).append(d)
    for img in images:
        img["documents"] = docs_by_image.get(img["imageId"], [])
    return images


def export_image(con: duckdb.DuckDBPyConnection, image_id: str) -> dict:
    """A single image scoped to ``image_id``, with its documents → pages nested."""
    images = _images_for(con, "id = ?", [image_id])
    if not images:
        return {}
    return {"image": images[0]}


def export_filing(con: duckdb.DuckDBPyConnection, filing_id: str) -> dict:
    """A filing-level export: the images linked to event ``filing_id`` via
    ``image_events`` (a many-to-many grouping — overlap with other filings is
    allowed), each image fully exploded. Returns the event header alongside its
    images."""
    event = _one(
        con,
        "SELECT id, date, event_type AS event, party, phase AS section "
        "FROM events WHERE id = ?",
        [filing_id],
    )
    if not event:
        return {}
    image_ids = [
        r["image_id"]
        for r in _rows(
            con,
            "SELECT image_id FROM image_events WHERE event_id = ?",
            [filing_id],
        )
    ]
    if image_ids:
        placeholders = ", ".join("?" for _ in image_ids)
        images = _images_for(con, f"id IN ({placeholders})", image_ids)
    else:
        images = []
    return {"filing": event, "images": images}


def export_exploded(
    con: duckdb.DuckDBPyConnection,
    *,
    image_id: str | None = None,
    document_id: str | None = None,
    page_id: str | None = None,
    filing_id: str | None = None,
) -> dict:
    """Build the Exploded-lens payload (read-only): case → image → document →
    page, each page carrying *every* current transcription variation beside it
    in a ``transcriptions`` list.

    With no selector this is the whole-case export ``{"images": [...]}``. Pass a
    selector to scope to one node:

    - ``page_id`` → :func:`export_page`
    - ``document_id`` → :func:`export_document`
    - ``image_id`` → :func:`export_image`
    - ``filing_id`` → :func:`export_filing` (the event's linked images)

    Each page's ``transcriptions`` is the **latest rev per
    ``(page_id, source, model)``**, ordered ground-truth first (``pdf_text``)
    then ``ai`` by model name; each entry carries ``source``, ``model``, ``rev``,
    ``createdAt``, ``fidelity``, and ``text``. An untranscribed page carries an
    empty list. The lens always shows the page image regardless.
    """
    if page_id is not None:
        return export_page(con, page_id)
    if document_id is not None:
        return export_document(con, document_id)
    if image_id is not None:
        return export_image(con, image_id)
    if filing_id is not None:
        return export_filing(con, filing_id)
    return {"images": _images_for(con)}
