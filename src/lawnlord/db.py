"""DuckDB index for the ``case -> event -> image -> document -> page`` model.

This is the **only SQL site**. The database is a derived index — a pure
function of the intake JSON plus the exploded corpus, fully regenerable. It
never authors content. ``apply_schema`` is idempotent and versioned;
``open_case_db`` opens (creating if needed) the per-case database file.

Vocabulary (source-true; glossary in docs/schema.md): an **image** is a filed PDF
(Odyssey's own term for it), and a **document** is a logical document *within*
an image (a Motion, an Exhibit, an Affidavit) — what the exploder detects as a
boundary section. So ``images`` holds the filed PDFs and ``documents`` holds the
documents-within; ``chunks`` (one row per page) link to both. Metadata ingestion
populates ``cases``/``parties``/``events``/``images``/``image_events`` (see
:mod:`lawnlord.ingest`); ``documents``/``chunks`` come from the corpus index step.
Entities/relationships/analysis are deferred to later milestones.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

# v2: re-leveled documents->images and sections->documents (docs/plans/v0.3.0).
# v3: landed the standard schema — case identity facets, financials +
#     financial_transactions, party aliases, and case_gaps.
# Per-case DBs are regenerable, so the bump needs no in-place migration.
# v4: chunks carry the page's text provenance (text_source, ocr_confidence) and
# a pointer to its preserved page image (page_image_path + page_image_sha256),
# so a page is reconstructable from the data alone (#31).
# v5: extracted_dates holds date-bearing facts found in page text (#36) — facts,
# not interpretations; every row is needs_review.
# v6: two-sided confidence (#33) — chunks carry confidence + ai_accessible +
# needs_review (scored against Odyssey metadata and the source PDFs), rolled up
# to documents.confidence and cases.confidence. Per-case DBs are regenerable, so
# the bumps need no in-place migration.
SCHEMA_VERSION = 6

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
        confidence DOUBLE,
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
    CREATE TABLE IF NOT EXISTS case_gaps (
        case_id TEXT NOT NULL,
        field TEXT NOT NULL,
        PRIMARY KEY (case_id, field)
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
    """
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        image_id TEXT NOT NULL,
        document_slug TEXT,
        document_index INTEGER,
        title TEXT,
        source_page_start INTEGER,
        source_page_end INTEGER,
        page_count INTEGER,
        boundary_confidence DOUBLE,
        detection_tier TEXT,
        document_family TEXT,
        needs_review BOOLEAN,
        confidence DOUBLE,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        image_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
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
        text_source TEXT,
        ocr_confidence DOUBLE,
        page_image_path TEXT,
        page_image_sha256 TEXT,
        ai_accessible BOOLEAN,
        needs_review BOOLEAN,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS extracted_dates (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        image_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        source_page_number INTEGER,
        date TEXT,
        raw_text TEXT,
        snippet TEXT,
        text_span_start INTEGER,
        text_span_end INTEGER,
        confidence DOUBLE,
        source TEXT,
        needs_review BOOLEAN,
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
