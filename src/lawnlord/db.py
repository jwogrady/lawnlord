"""DuckDB index for the case record read from the deterministic intake zip.

This is the **only SQL site**. The database is a derived index — a pure
function of the intake zip, fully regenerable. It never authors content.
``apply_schema`` is idempotent and versioned; ``open_case_db`` opens (creating
if needed) the per-case database file.

Vocabulary (glossary in docs/schema.md): an **image** is a filed PDF (the
court's leaf). The schema is the **relational mirror of the zip's** ``data.json``
— seven tables: ``cases``, ``parties``, ``events``, ``images``, ``image_events``,
``financials``, ``financial_transactions`` — all populated by
:mod:`lawnlord.ingest` from the validated ``CaseModel``. The Exploded lens (its
documents/pages + transcription) and any analysis arrive later as clearly
additive layers, not in this mirror.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

# v7 (alpha pivot): re-scoped to the zip standard — the schema is now exactly the
# relational mirror of data.json (the seven tables above). The pre-pivot additive
# tables (case_gaps, documents, chunks, extracted_dates, knowledge_documents) and
# the cases.confidence scoring column were dropped; they belonged to the removed
# explosion/reconstruction/confidence layers. Per-case DBs are regenerable, so the
# bump needs no in-place migration.
SCHEMA_VERSION = 7

# One statement per table; CREATE ... IF NOT EXISTS keeps apply_schema idempotent.
_SCHEMA_STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)",
    """
    CREATE TABLE IF NOT EXISTS cases (
        id TEXT PRIMARY KEY,
        title TEXT,
        court TEXT,
        clerk TEXT,
        judicial_officer TEXT,
        case_type TEXT,
        case_category TEXT,
        status TEXT,
        date_filed TEXT,
        citation_number TEXT,
        disposition_type TEXT,
        disposition_date TEXT,
        disposition_comment TEXT,
        source_url TEXT,
        last_refreshed TEXT,
        source_note TEXT,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS parties (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        role TEXT,
        name TEXT,
        representation TEXT,
        attorneys TEXT,
        aliases TEXT,
        location TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS financials (
        case_id TEXT PRIMARY KEY,
        party TEXT,
        total_assessment TEXT,
        total_payments TEXT,
        balance_due TEXT,
        balance_as_of TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS financial_transactions (
        case_id TEXT NOT NULL,
        idx INTEGER NOT NULL,
        date TEXT,
        description TEXT,
        amount TEXT,
        PRIMARY KEY (case_id, idx)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        date TEXT,
        phase TEXT,
        event_type TEXT,
        description TEXT,
        party TEXT,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS images (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        filename TEXT,
        title TEXT,
        intake_path TEXT,
        docket_type TEXT,
        filing_date TEXT,
        declared_page_count INTEGER,
        actual_page_count INTEGER,
        page_count_mismatch BOOLEAN,
        sha256_hash TEXT NOT NULL,
        needs_review BOOLEAN,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS image_events (
        image_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        PRIMARY KEY (image_id, event_id)
    )
    """,
)


def open_case_db(
    path: str | Path, read_only: bool = False
) -> duckdb.DuckDBPyConnection:
    """Open the per-case DuckDB database at ``path``.

    Read-write by default (creating the file and parent dirs if needed);
    pass ``read_only=True`` for queries, which requires an existing database.
    """
    path = Path(path)
    if read_only:
        if not path.exists():
            raise FileNotFoundError(f"case database not found: {path}")
        return duckdb.connect(str(path), read_only=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def apply_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Apply the versioned M1 schema. Idempotent: running twice is a no-op."""
    for statement in _SCHEMA_STATEMENTS:
        con.execute(statement)
    row = con.execute("SELECT count(*) FROM schema_meta").fetchone()
    if row[0] == 0:
        con.execute("INSERT INTO schema_meta (version) VALUES (?)", [SCHEMA_VERSION])


def load_fts(con: duckdb.DuckDBPyConnection) -> bool:
    """Best-effort load of the DuckDB full-text-search extension. Returns True if
    it is available. ``LOAD`` alone suffices once installed (and works offline);
    ``INSTALL`` needs network the first time only. Failure is non-fatal — callers
    fall back to a substring scan, so search always works."""
    try:
        con.execute("LOAD fts")
        return True
    except Exception:
        pass
    try:
        con.execute("INSTALL fts")
        con.execute("LOAD fts")
        return True
    except Exception:
        return False
