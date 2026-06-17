"""DuckDB index for the ``case -> event -> document -> section -> page`` model.

This is the **only SQL site**. The database is a derived index — a pure
function of the intake JSON plus the exploded corpus, fully regenerable. It
never authors content. ``apply_schema`` is idempotent and versioned;
``open_case_db`` opens (creating if needed) the per-case database file.

The M1 schema covers identity/docket (``cases``, ``parties``, ``events``,
``documents``, ``document_events``) plus the exploder layer (``sections``,
``chunks``); entities/relationships/analysis are deferred to later milestones.
Metadata ingestion populates the docket tables (see :mod:`lawnlord.ingest`);
``sections``/``chunks`` are populated by the corpus index step.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA_VERSION = 1

# One statement per table; CREATE ... IF NOT EXISTS keeps apply_schema idempotent.
_SCHEMA_STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)",
    """
    CREATE TABLE IF NOT EXISTS cases (
        id TEXT PRIMARY KEY,
        title TEXT,
        court TEXT,
        judicial_officer TEXT,
        case_type TEXT,
        status TEXT,
        date_filed TEXT,
        disposition_type TEXT,
        disposition_date TEXT,
        source_url TEXT,
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
        location TEXT
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
    CREATE TABLE IF NOT EXISTS documents (
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
    CREATE TABLE IF NOT EXISTS document_events (
        document_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        PRIMARY KEY (document_id, event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sections (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        section_slug TEXT,
        section_index INTEGER,
        title TEXT,
        source_page_start INTEGER,
        source_page_end INTEGER,
        page_count INTEGER,
        boundary_confidence DOUBLE,
        detection_tier TEXT,
        document_family TEXT,
        needs_review BOOLEAN,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        section_id TEXT NOT NULL,
        text TEXT,
        page_number INTEGER,
        source_page_number INTEGER,
        paragraph_number INTEGER,
        text_span_start INTEGER,
        text_span_end INTEGER,
        extraction_method TEXT,
        citation_low TEXT,
        citation_display TEXT,
        confidence DOUBLE,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_documents (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        title TEXT,
        source_path TEXT,
        created_at TEXT
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
