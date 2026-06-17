"""Ingest a :class:`~lawnlord.workspace.Case` into the DuckDB index.

Populates the docket tables — ``cases``, ``parties``, ``events``,
``documents``, ``document_events`` — straight from the curated intake metadata.
Identity, dates, docket types, and parties come from the JSON; this step never
guesses and parses no PDF content (it only hashes document bytes so document
IDs match the exploder's ``doc_<sha16>`` scheme).

Determinism: every ``created_at`` is the caller-supplied ``generated_at`` (never
wall-clock), IDs derive from stable inputs, and ingest is drop-and-rebuild for
the case's docket rows — so re-ingesting identical inputs is byte-identical.
"""

from __future__ import annotations

import json

import duckdb
from slugify import slugify

from .hashing import sha256_file
from .workspace import Case


def _event_id(case_id: str, date: str, event: str, used: set[str]) -> str:
    """Stable, unique, slugified event id ``{case}-{date}-{event}``.

    Events that share a ``(date, event)`` — e.g. service on two defendants, or a
    routine event logged several times in a day — get a deterministic numeric
    suffix (``-2``, ``-3``, …) so any number of duplicates stay collision-free.
    """
    base = slugify(f"{case_id}_{date}_{event}") or "event"
    candidate = base
    n = 2
    while candidate in used:
        candidate = f"{base}-{n}"
        n += 1
    used.add(candidate)
    return candidate


def _clear_case(con: duckdb.DuckDBPyConnection, case_id: str) -> None:
    """Drop this case's docket rows for a clean rebuild. The database is
    one-per-case; ``document_events`` (no ``case_id`` of its own) is scoped via
    this case's documents so a shared DB would not lose another case's links."""
    con.execute(
        "DELETE FROM document_events WHERE document_id IN "
        "(SELECT id FROM documents WHERE case_id = ?)",
        [case_id],
    )
    con.execute("DELETE FROM documents WHERE case_id = ?", [case_id])
    con.execute("DELETE FROM events WHERE case_id = ?", [case_id])
    con.execute("DELETE FROM parties WHERE case_id = ?", [case_id])
    con.execute("DELETE FROM cases WHERE id = ?", [case_id])


def ingest_case(con: duckdb.DuckDBPyConnection, case: Case, generated_at: str) -> dict:
    """Ingest the docket metadata for ``case``. Returns row counts.

    Documents whose source PDF is missing (cannot be hashed) are skipped and
    reported in the returned ``skipped_documents`` list rather than inserted
    with a fabricated hash.
    """
    ident = case.identity
    case_id = ident.case_number or case.case_slug
    _clear_case(con, case_id)

    con.execute(
        """
        INSERT INTO cases (id, title, court, judicial_officer, case_type, status,
                           date_filed, disposition_type, disposition_date,
                           source_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            case_id, ident.title, ident.court, ident.judicial_officer,
            ident.case_type, ident.status, ident.date_filed,
            ident.disposition_type, ident.disposition_date, ident.source_url,
            generated_at,
        ],
    )

    for i, party in enumerate(case.parties):
        con.execute(
            """
            INSERT INTO parties (id, case_id, role, name, representation,
                                 attorneys, location)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                f"{case_id}_party_{i:03d}", case_id, party.role, party.name,
                party.representation,
                json.dumps([a.__dict__ for a in party.attorneys]),
                party.location,
            ],
        )

    # Events: keep id -> files so document_events can be linked after documents.
    used_event_ids: set[str] = set()
    event_files: list[tuple[str, tuple[str, ...]]] = []
    for event in case.events:
        event_id = _event_id(case_id, event.date, event.event, used_event_ids)
        con.execute(
            """
            INSERT INTO events (id, case_id, date, phase, event_type, description,
                                party, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                event_id, case_id, event.date, event.phase, event.event,
                event.description, event.party, generated_at,
            ],
        )
        event_files.append((event_id, event.files))

    # Documents: dedupe by content hash; map intake path -> document id.
    path_to_doc: dict[str, str] = {}
    seen_docs: set[str] = set()
    skipped: list[str] = []
    for doc in case.documents:
        pdf_path = case.intake_dir / doc.intake_path
        if not pdf_path.exists():
            skipped.append(doc.intake_path)
            continue
        sha = sha256_file(pdf_path)
        doc_id = f"doc_{sha[:16]}"
        path_to_doc[doc.intake_path] = doc_id
        if doc_id in seen_docs:
            continue  # same bytes under another path — one document row
        seen_docs.add(doc_id)
        con.execute(
            """
            INSERT INTO documents (id, case_id, filename, title, intake_path,
                                   docket_type, filing_date, declared_page_count,
                                   actual_page_count, page_count_mismatch,
                                   sha256_hash, needs_review, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, ?)
            """,
            [
                doc_id, case_id, doc.filename, doc.title, doc.intake_path,
                doc.docket_event, doc.filing_date, doc.declared_page_count,
                sha, generated_at,
            ],
        )

    # Many-to-many: link each event to the documents named in its files[].
    used_links: set[tuple[str, str]] = set()
    for event_id, files in event_files:
        for intake_path in files:
            doc_id = path_to_doc.get(intake_path)
            if doc_id is None or (doc_id, event_id) in used_links:
                continue
            used_links.add((doc_id, event_id))
            con.execute(
                "INSERT INTO document_events (document_id, event_id) VALUES (?, ?)",
                [doc_id, event_id],
            )

    return {
        "cases": 1,
        "parties": len(case.parties),
        "events": len(event_files),
        "documents": len(seen_docs),
        "document_events": len(used_links),
        "skipped_documents": skipped,
    }
