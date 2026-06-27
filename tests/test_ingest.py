"""``ingest_case`` edge-path coverage (#162), driven directly on a DuckDB
connection so each branch is isolated from the import CLI wrapper.

Covers: a document whose source PDF is absent is reported (not inserted with a
fabricated hash); two intake paths pointing at identical bytes collapse to one
image row; events sharing ``(date, event)`` get deterministic ``-2``/``-3`` id
suffixes; the optional financials/transactions block ingests; and re-ingesting
identical inputs is idempotent (drop-and-rebuild yields identical row counts).
"""

import copy
import json

import lawnlord as main

from test_reader import _GOOD_CASE, _SCHEMA


def _write_intake(tmp_path, case, files):
    """Build an extracted intake dir with the given case dict and {path: bytes}."""
    d = tmp_path / "intake"
    (d / "files").mkdir(parents=True)
    (d / "data.json").write_text(json.dumps([case]), encoding="utf-8")
    (d / "schema.json").write_text(json.dumps(_SCHEMA), encoding="utf-8")
    (d / "manifest.json").write_text(
        json.dumps({"capturedAt": "2026-06-20T16:42:56Z"}), encoding="utf-8"
    )
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    return d


def _ingest(tmp_path_factory_dir, case, files):
    intake = _write_intake(tmp_path_factory_dir, case, files)
    case_obj = main.Case.from_intake(intake, case_dir=tmp_path_factory_dir / "out")
    con = main.open_case_db(case_obj.duckdb_path)
    main.apply_schema(con)
    stats = main.ingest_case(con, case_obj, main.captured_at(intake))
    return con, stats


def test_absent_source_pdf_is_skipped_not_fabricated(tmp_path):
    # data.json references doc-1.pdf but no bytes are written for it.
    con, stats = _ingest(tmp_path, _GOOD_CASE, files={})
    try:
        assert stats["skipped_images"] == ["files/doc-1.pdf"]
        assert stats["images"] == 0
        assert con.execute("SELECT count(*) FROM images").fetchone()[0] == 0
    finally:
        con.close()


def test_identical_bytes_under_two_paths_yield_one_image(tmp_path):
    same = b"%PDF-1.4\n%identical bytes\n%%EOF"
    case = copy.deepcopy(_GOOD_CASE)
    case["documents"] = [
        {"Image": "First", "Page Count": "1", "date": "01/02/2025",
         "event": "E-Filed Original Petition", "file": "files/a.pdf"},
        {"Image": "Second", "Page Count": "1", "date": "01/03/2025",
         "event": "E-Filed Second", "file": "files/b.pdf"},
    ]
    con, stats = _ingest(tmp_path, case,
                         files={"files/a.pdf": same, "files/b.pdf": same})
    try:
        assert stats["images"] == 1  # deduped by content hash
        assert con.execute("SELECT count(*) FROM images").fetchone()[0] == 1
    finally:
        con.close()


def test_duplicate_date_event_get_deterministic_suffixes(tmp_path):
    case = copy.deepcopy(_GOOD_CASE)
    # Three register entries sharing the same (date, event).
    case["registerOfActions"] = [
        {"date": "01/02/2025", "event": "Service Issued",
         "section": "other events and hearings"},
        {"date": "01/02/2025", "event": "Service Issued",
         "section": "other events and hearings"},
        {"date": "01/02/2025", "event": "Service Issued",
         "section": "other events and hearings"},
    ]
    case["documents"] = []
    con, stats = _ingest(tmp_path, case, files={})
    try:
        assert stats["events"] == 3
        ids = [r[0] for r in con.execute("SELECT id FROM events ORDER BY id").fetchall()]
        # base, base-2, base-3 — collision-free, deterministic suffixes.
        assert len(set(ids)) == 3
        suffixed = [i for i in ids if i.endswith("-2") or i.endswith("-3")]
        assert len(suffixed) == 2
    finally:
        con.close()


def test_financials_and_transactions_block_ingests(tmp_path):
    # _GOOD_CASE carries a financial block with one transaction.
    con, stats = _ingest(tmp_path, _GOOD_CASE,
                         files={"files/doc-1.pdf": b"%PDF-1.4\n%x\n%%EOF"})
    try:
        assert con.execute("SELECT count(*) FROM financials").fetchone()[0] == 1
        assert con.execute(
            "SELECT count(*) FROM financial_transactions"
        ).fetchone()[0] == 1
        amount = con.execute(
            "SELECT amount FROM financial_transactions"
        ).fetchone()[0]
        assert amount == "366.00"
    finally:
        con.close()


def test_reingest_is_idempotent(tmp_path):
    files = {"files/doc-1.pdf": b"%PDF-1.4\n%x\n%%EOF"}
    intake = _write_intake(tmp_path, _GOOD_CASE, files)
    case_obj = main.Case.from_intake(intake, case_dir=tmp_path / "out")
    con = main.open_case_db(case_obj.duckdb_path)
    main.apply_schema(con)
    generated_at = main.captured_at(intake)

    def counts():
        return {
            t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("cases", "parties", "events", "images", "image_events",
                      "financials", "financial_transactions")
        }

    try:
        main.ingest_case(con, case_obj, generated_at)
        first = counts()
        # Drop-and-rebuild: re-ingesting identical inputs yields identical counts.
        main.ingest_case(con, case_obj, generated_at)
        assert counts() == first
        assert first["cases"] == 1
    finally:
        con.close()
