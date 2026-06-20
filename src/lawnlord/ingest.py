"""Ingest a :class:`~lawnlord.workspace.Case` into the DuckDB index.

Populates the docket tables — ``cases``, ``parties``, ``events``, ``images``,
``image_events``, ``financials`` — straight from the ``CaseModel`` read from the
intake zip's ``data.json``. An **image** is a filed PDF; the documents *within*
each image are the future Exploded view's job. Identity, dates, docket types,
and parties come from the model; this step never guesses and parses no PDF
content (it only hashes image bytes, so image IDs are stable content hashes,
``doc_<sha16>``).

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
    one-per-case; ``image_events`` (no ``case_id`` of its own) is scoped via
    this case's images so a shared DB would not lose another case's links."""
    con.execute(
        "DELETE FROM image_events WHERE image_id IN "
        "(SELECT id FROM images WHERE case_id = ?)",
        [case_id],
    )
    con.execute("DELETE FROM images WHERE case_id = ?", [case_id])
    con.execute("DELETE FROM events WHERE case_id = ?", [case_id])
    con.execute("DELETE FROM parties WHERE case_id = ?", [case_id])
    con.execute("DELETE FROM financial_transactions WHERE case_id = ?", [case_id])
    con.execute("DELETE FROM financials WHERE case_id = ?", [case_id])
    con.execute("DELETE FROM case_gaps WHERE case_id = ?", [case_id])
    con.execute("DELETE FROM cases WHERE id = ?", [case_id])


def ingest_case(con: duckdb.DuckDBPyConnection, case: Case, generated_at: str) -> dict:
    """Ingest the docket metadata for ``case``. Returns row counts.

    Documents whose source PDF is missing (cannot be hashed) are skipped and
    reported in the returned ``skipped_images`` list rather than inserted
    with a fabricated hash.
    """
    # The zip is the deterministic single source; the model is consumed as-is
    # (no multi-source unification — that was a provider-era concern).
    model = case.model
    ident = model.identity
    case_id = ident.case_number or case.case_slug
    _clear_case(con, case_id)

    con.execute(
        """
        INSERT INTO cases (id, title, court, clerk, judicial_officer, case_type,
                           case_category, status, date_filed, citation_number,
                           disposition_type, disposition_date, disposition_comment,
                           source_url, last_refreshed, source_note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            case_id, ident.title, ident.court, ident.clerk,
            ident.judicial_officer, ident.case_type, ident.case_category,
            ident.status, ident.date_filed, ident.citation_number,
            ident.disposition_type, ident.disposition_date,
            ident.disposition_comment, ident.source_url, ident.last_refreshed,
            model.source_note, generated_at,
        ],
    )

    for i, party in enumerate(model.parties):
        con.execute(
            """
            INSERT INTO parties (id, case_id, role, name, representation,
                                 attorneys, aliases, location)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                f"{case_id}_party_{i:03d}", case_id, party.role, party.name,
                party.representation,
                json.dumps([a.__dict__ for a in party.attorneys]),
                json.dumps(list(party.aliases)),
                party.location,
            ],
        )

    if model.financials is not None:
        fin = model.financials
        con.execute(
            """
            INSERT INTO financials (case_id, party, total_assessment,
                                    total_payments, balance_due, balance_as_of)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                case_id, fin.party, fin.total_assessment, fin.total_payments,
                fin.balance_due, fin.balance_as_of,
            ],
        )
        for i, t in enumerate(fin.transactions):
            con.execute(
                "INSERT INTO financial_transactions (case_id, idx, date, "
                "description, amount) VALUES (?, ?, ?, ?, ?)",
                [case_id, i, t.date, t.description, t.amount],
            )

    # Events: keep id -> files so image_events can be linked after images.
    used_event_ids: set[str] = set()
    event_files: list[tuple[str, tuple[str, ...]]] = []
    for event in model.events:
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

    # Images (filed PDFs): dedupe by content hash; map intake path -> image id.
    path_to_image: dict[str, str] = {}
    seen_images: set[str] = set()
    skipped: list[str] = []
    for doc in model.documents:
        pdf_path = case.intake_dir / doc.intake_path
        if not pdf_path.exists():
            skipped.append(doc.intake_path)
            continue
        sha = sha256_file(pdf_path)
        image_id = f"doc_{sha[:16]}"
        path_to_image[doc.intake_path] = image_id
        if image_id in seen_images:
            continue  # same bytes under another path — one image row
        seen_images.add(image_id)
        con.execute(
            """
            INSERT INTO images (id, case_id, filename, title, intake_path,
                                docket_type, filing_date, declared_page_count,
                                actual_page_count, page_count_mismatch,
                                sha256_hash, needs_review, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, ?)
            """,
            [
                image_id, case_id, doc.filename, doc.title, doc.intake_path,
                doc.docket_event, doc.filing_date, doc.declared_page_count,
                sha, generated_at,
            ],
        )

    # Many-to-many: link each event (filing) to the images named in its files[].
    used_links: set[tuple[str, str]] = set()
    for event_id, files in event_files:
        for intake_path in files:
            image_id = path_to_image.get(intake_path)
            if image_id is None or (image_id, event_id) in used_links:
                continue
            used_links.add((image_id, event_id))
            con.execute(
                "INSERT INTO image_events (image_id, event_id) VALUES (?, ?)",
                [image_id, event_id],
            )

    return {
        "cases": 1,
        "parties": len(model.parties),
        "events": len(event_files),
        "images": len(seen_images),
        "image_events": len(used_links),
        "skipped_images": skipped,
    }
