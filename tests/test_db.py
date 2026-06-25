"""DuckDB schema: creation and idempotency."""

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
