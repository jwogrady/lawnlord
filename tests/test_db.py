"""DuckDB schema: creation and idempotency."""

import lawnlord as main

_M1_TABLES = {
    "schema_meta", "cases", "parties", "events", "documents",
    "document_events", "sections", "chunks", "knowledge_documents",
}


def _table_names(con):
    return {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def test_apply_schema_creates_all_tables(tmp_path):
    con = main.open_case_db(tmp_path / "lawnlord.duckdb")
    main.apply_schema(con)
    assert _M1_TABLES <= _table_names(con)


def test_apply_schema_is_idempotent(tmp_path):
    con = main.open_case_db(tmp_path / "lawnlord.duckdb")
    main.apply_schema(con)
    main.apply_schema(con)  # second run must be a no-op
    assert _table_names(con) >= _M1_TABLES
    # schema_meta records exactly one version row.
    assert con.execute("SELECT count(*) FROM schema_meta").fetchone()[0] == 1
    assert con.execute("SELECT version FROM schema_meta").fetchone()[0] == main.SCHEMA_VERSION


def test_open_case_db_creates_parent_dirs(tmp_path):
    db_path = tmp_path / "nested" / "deeper" / "lawnlord.duckdb"
    con = main.open_case_db(db_path)
    main.apply_schema(con)
    assert db_path.exists()
