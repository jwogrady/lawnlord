"""DuckDB schema: creation and idempotency."""

import lawnlord as main

# The re-scoped schema is exactly the relational mirror of the zip's data.json.
_MIRROR_TABLES = {
    "schema_meta", "cases", "parties", "events", "images",
    "image_events", "financials", "financial_transactions",
}


def _table_names(con):
    return {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def test_apply_schema_creates_exactly_the_mirror_tables(tmp_path):
    con = main.open_case_db(tmp_path / "lawnlord.duckdb")
    main.apply_schema(con)
    assert _table_names(con) == _MIRROR_TABLES


def test_apply_schema_is_idempotent(tmp_path):
    con = main.open_case_db(tmp_path / "lawnlord.duckdb")
    main.apply_schema(con)
    main.apply_schema(con)  # second run must be a no-op
    assert _table_names(con) == _MIRROR_TABLES
    # schema_meta records exactly one version row.
    assert con.execute("SELECT count(*) FROM schema_meta").fetchone()[0] == 1
    assert con.execute("SELECT version FROM schema_meta").fetchone()[0] == main.SCHEMA_VERSION


def test_open_case_db_creates_parent_dirs(tmp_path):
    db_path = tmp_path / "nested" / "deeper" / "lawnlord.duckdb"
    con = main.open_case_db(db_path)
    main.apply_schema(con)
    assert db_path.exists()
