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
