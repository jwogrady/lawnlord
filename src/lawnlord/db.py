"""DuckDB index for the case record read from the deterministic intake zip.

This is the **only SQL site**. The database is a derived index — a pure
function of the intake zip, fully regenerable. It never authors content.
``apply_schema`` is idempotent and versioned; ``open_case_db`` opens (creating
if needed) the per-case database file.

Vocabulary (glossary in docs/schema.md): an **image** is a filed PDF (the
court's leaf). The **mirror** is the relational mirror of the zip's ``data.json``
— seven tables: ``cases``, ``parties``, ``events``, ``images``, ``image_events``,
``financials``, ``financial_transactions`` — all populated by
:mod:`lawnlord.ingest` from the validated ``CaseModel``.

On top of the mirror sits the **Exploded layer** — ``documents`` (one per image)
and ``pages`` (one per rendered page, with its PNG pointer), populated by
:mod:`lawnlord.explode`; and ``page_text`` — the **append-only** AI transcription
of each page (rev 0 immutable; re-runs append a revision), populated by
:mod:`lawnlord.transcribe`. Above that sits the **spatial-anchor layer** —
``page_regions`` (ADR-0009): a bounding box per text span, anchored to a source
row via a generic ``(anchor_kind, anchor_id)``, populated by
:mod:`lawnlord.regions`. All additive: they reference the mirror but never mutate
it. Analysis is a later additive layer.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

# v7 (alpha pivot): re-scoped to the zip standard — the mirror is exactly the
# relational mirror of data.json (the seven tables above). The pre-pivot additive
# tables and the cases.confidence column were dropped.
# v8 (F3): the Exploded layer — `documents` (one per image) + `pages` (one per
# rendered page, with its PNG pointer) — added on top of the mirror. Additive:
# references the mirror's images, never mutates them.
# v9 (F4): `page_text` — append-only AI transcription per page (rev 0 immutable).
# Per-case DBs are regenerable, so bumps need no in-place migration.
# v10 (ADR-0005): re-key `page_text` on a surrogate `id` (content hash of
# page_id|source|model|rev) so one page holds *every* transcription variation —
# the PDF text layer plus one row per vision model — each individually
# addressable, instead of a single (page_id, rev) lineage. Regenerable: re-import.
# v11 (ADR-0009): `page_regions` — an additive, generic page-region primitive
# (bounding boxes per text span, normalized 0..1 top-left) anchored to a source
# row's stable id (`anchor_kind`/`anchor_id`: a `page_text` variation today, an
# analysis entity later). Populated from PDF geometry for born-digital pages;
# never fabricated. Additive: references pages/page_text, never mutates them.
SCHEMA_VERSION = 11

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
    # --- Exploded layer (additive; references images, never mutates them) ---
    """
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        image_id TEXT NOT NULL,
        title TEXT,
        page_count INTEGER,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pages (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        image_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        page_number INTEGER NOT NULL,
        page_image_path TEXT,
        page_image_sha256 TEXT,
        created_at TEXT
    )
    """,
    # Append-only AI transcription per page, keyed on a surrogate content-hash
    # `id` (ADR-0005, v10) so a page holds every variation — the PDF text layer
    # plus one row per vision model — each addressable. Append-only *per
    # variation*: rev 0 of a given (page_id, source, model) is immutable; a re-run
    # appends the next rev within that variation. Never overwrites.
    """
    CREATE TABLE IF NOT EXISTS page_text (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        page_id TEXT NOT NULL,
        rev INTEGER NOT NULL,
        source TEXT,
        text TEXT,
        fidelity DOUBLE,
        model TEXT,
        created_at TEXT
    )
    """,
    # Spatial-anchor layer (ADR-0009): bounding boxes per text span, anchored to a
    # source row's stable id via (anchor_kind, anchor_id) — a `page_text` variation
    # today, an analysis entity later — so it is a *general* page-region primitive,
    # not transcription-specific. Coordinates are normalized 0..1 with a top-left
    # origin (resolution-independent: they overlay the rendered PNG at any DPI).
    # `char_start`/`char_end` index the anchor's text (the span this box covers).
    # Additive and deterministic: ids/ordering hash structure only, never the
    # (possibly model-supplied) coordinates. A span with no reliable geometry is
    # simply absent — a region is never fabricated.
    """
    CREATE TABLE IF NOT EXISTS page_regions (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        page_id TEXT NOT NULL,
        anchor_id TEXT NOT NULL,
        anchor_kind TEXT NOT NULL,
        span_index INTEGER NOT NULL,
        char_start INTEGER,
        char_end INTEGER,
        x0 DOUBLE NOT NULL,
        y0 DOUBLE NOT NULL,
        x1 DOUBLE NOT NULL,
        y1 DOUBLE NOT NULL,
        origin TEXT NOT NULL,
        confidence DOUBLE,
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


class SchemaVersionMismatch(RuntimeError):
    """A per-case DB was stamped by a different ``SCHEMA_VERSION`` than the code
    opening it. The DB is a regenerable index, so the fix is always to regenerate
    it (re-run the import) — never to silently proceed against a stale schema."""


def apply_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Apply the versioned M1 schema. Idempotent: running twice is a no-op.

    Refuses to proceed if the DB was stamped by a different ``SCHEMA_VERSION``
    (older or newer): a per-case DB is a derived index, so a mismatch means the
    operator must regenerate it (re-run the import) rather than risk
    misreporting provenance against a stale schema.
    """
    for statement in _SCHEMA_STATEMENTS:
        con.execute(statement)
    row = con.execute("SELECT version FROM schema_meta").fetchone()
    if row is None:
        con.execute("INSERT INTO schema_meta (version) VALUES (?)", [SCHEMA_VERSION])
        return
    stored = row[0]
    if stored != SCHEMA_VERSION:
        raise SchemaVersionMismatch(
            f"schema version mismatch: this database was stamped v{stored}, "
            f"but the code expects v{SCHEMA_VERSION}. Per-case databases are a "
            "regenerable index — regenerate this one (re-run the import) instead "
            "of opening it with mismatched code."
        )


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
