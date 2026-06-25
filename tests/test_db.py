"""DuckDB schema: creation and idempotency."""

import subprocess
import sys
import textwrap

import pytest

import lawnlord as main

# The relational mirror of the zip's data.json (always present). The Exploded
# layer (documents, pages) is additive on top.
_MIRROR_TABLES = {
    "schema_meta", "cases", "parties", "events", "images",
    "image_events", "financials", "financial_transactions",
}
_EXPLODED_TABLES = {"documents", "pages", "page_text"}
# Spatial-anchor layer (ADR-0009): boxes per text span, additive on the above.
_SPATIAL_TABLES = {"page_regions"}
_ALL_TABLES = _MIRROR_TABLES | _EXPLODED_TABLES | _SPATIAL_TABLES


def _table_names(con):
    return {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def test_apply_schema_creates_the_mirror_and_exploded_tables(tmp_path):
    con = main.open_case_db(tmp_path / "lawnlord.duckdb")
    main.apply_schema(con)
    assert _table_names(con) == _ALL_TABLES


def test_apply_schema_is_idempotent(tmp_path):
    con = main.open_case_db(tmp_path / "lawnlord.duckdb")
    main.apply_schema(con)
    main.apply_schema(con)  # second run must be a no-op
    assert _table_names(con) == _ALL_TABLES
    # schema_meta records exactly one version row.
    assert con.execute("SELECT count(*) FROM schema_meta").fetchone()[0] == 1
    assert con.execute("SELECT version FROM schema_meta").fetchone()[0] == main.SCHEMA_VERSION


def test_apply_schema_refuses_older_stamped_version(tmp_path):
    """A DB stamped by an older SCHEMA_VERSION (e.g. a v9 .bak opened by v11
    code) must fail loudly naming both versions, not silently append rows."""
    con = main.open_case_db(tmp_path / "lawnlord.duckdb")
    main.apply_schema(con)
    stale = main.SCHEMA_VERSION - 2
    con.execute("UPDATE schema_meta SET version = ?", [stale])
    with pytest.raises(main.SchemaVersionMismatch) as excinfo:
        main.apply_schema(con)
    message = str(excinfo.value)
    assert str(stale) in message
    assert str(main.SCHEMA_VERSION) in message
    # The refusal must not have appended a second row.
    assert con.execute("SELECT count(*) FROM schema_meta").fetchone()[0] == 1


def test_apply_schema_refuses_future_stamped_version(tmp_path):
    """A DB from the future (stored > SCHEMA_VERSION) is refused too."""
    con = main.open_case_db(tmp_path / "lawnlord.duckdb")
    main.apply_schema(con)
    con.execute("UPDATE schema_meta SET version = ?", [main.SCHEMA_VERSION + 1])
    with pytest.raises(main.SchemaVersionMismatch):
        main.apply_schema(con)


def test_open_case_db_creates_parent_dirs(tmp_path):
    db_path = tmp_path / "nested" / "deeper" / "lawnlord.duckdb"
    con = main.open_case_db(db_path)
    main.apply_schema(con)
    assert db_path.exists()


def _hold_writer(db_path):
    """Spawn a child process that opens a read-write connection and blocks,
    holding DuckDB's single-writer file lock. DuckDB's lock is cross-*process*
    (a second connection in the same process is just reused), so contention can
    only be exercised from a separate OS process."""
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(f"""
                import duckdb, sys, time
                con = duckdb.connect({str(db_path)!r})
                print("HELD", flush=True)
                time.sleep(30)
            """),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    # Block until the child confirms it holds the lock.
    line = child.stdout.readline().strip()
    assert line == "HELD", f"writer child failed to start: {line!r}"
    return child


@pytest.mark.parametrize("read_only", [False, True])
def test_open_case_db_reports_lock_contention(tmp_path, read_only):
    """A second open of a case file held by another writer must raise the
    friendly CaseDatabaseBusy (write *and* read-only), not a raw DuckDB
    IOException — DuckDB refuses both while a writer holds the lock."""
    db_path = tmp_path / "lawnlord.duckdb"
    # Create the file first so a read-only open gets past the existence check
    # and actually reaches the lock.
    main.open_case_db(db_path).close()

    writer = _hold_writer(db_path)
    try:
        with pytest.raises(main.CaseDatabaseBusy) as excinfo:
            main.open_case_db(db_path, read_only=read_only)
        message = str(excinfo.value)
        assert str(db_path) in message
        assert "another lawnlord process is writing" in message.lower()
    finally:
        writer.terminate()
        writer.wait(timeout=10)


def test_open_case_db_missing_is_not_busy(tmp_path):
    """A genuinely missing read-only DB is a FileNotFoundError, distinct from
    lock contention — the busy path must not mask a missing/corrupt file."""
    with pytest.raises(FileNotFoundError):
        main.open_case_db(tmp_path / "absent.duckdb", read_only=True)
