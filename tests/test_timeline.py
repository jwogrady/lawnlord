"""The factual timeline (#30): docket events + extracted date facts, derived
only from the record — sorted, undated separated, deadline-like items flagged.
"""

import lawnlord as main
from lawnlord import cli
from lawnlord.query import timeline


def _event(con, eid, date, event_type, description="", phase="", party=""):
    con.execute(
        "INSERT INTO events (id, case_id, date, phase, event_type, description, "
        "party, created_at) VALUES (?, 'c', ?, ?, ?, ?, ?, 't')",
        [eid, date, phase, event_type, description, party],
    )


def test_timeline_sorts_dated_and_separates_undated(tmp_path):
    con = main.open_case_db(tmp_path / "t.duckdb")
    main.apply_schema(con)
    _event(con, "e1", "2025-03-01", "Motion for Summary Judgment")
    _event(con, "e2", "2025-01-01", "Original Petition")
    _event(con, "e3", "", "Unfiled note")  # no date in the record
    tl = timeline(con)
    con.close()
    assert [i["date"] for i in tl["dated"]] == ["2025-01-01", "2025-03-01"]
    assert all(i["date"] for i in tl["dated"])  # none blank
    assert [i["label"] for i in tl["undated"]] == ["Unfiled note"]  # separated, not invented


def test_timeline_flags_deadline_like_items(tmp_path):
    con = main.open_case_db(tmp_path / "t.duckdb")
    main.apply_schema(con)
    _event(con, "e1", "2026-02-01", "Bench Trial", description="Bench Trial (canceled)")
    _event(con, "e2", "2025-01-01", "Original Petition")
    flags = {i["label"]: i["flag"] for i in timeline(con)["dated"]}
    con.close()
    assert flags["Bench Trial"] is True  # trial -> surfaced for review
    assert flags["Original Petition"] is False


def test_timeline_merges_docket_and_extracted_with_provenance(tmp_path):
    con = main.open_case_db(tmp_path / "t.duckdb")
    main.apply_schema(con)
    _event(con, "e1", "2025-01-01", "Original Petition")
    con.execute(
        "INSERT INTO extracted_dates (id, case_id, image_id, document_id, "
        "source_page_number, date, raw_text, snippet, text_span_start, "
        "text_span_end, confidence, source, needs_review, created_at) VALUES "
        "('d1','c','img1','doc1',4,'2026-03-10','03/10/2026',"
        "'Trial set for 03/10/2026',0,10,0.9,'extracted',TRUE,'t')"
    )
    tl = timeline(con)
    con.close()
    assert {i["source"] for i in tl["dated"]} == {"docket", "extracted"}
    extracted = next(i for i in tl["dated"] if i["source"] == "extracted")
    assert extracted["date"] == "2026-03-10"
    assert extracted["detail"] == "img1 p.4"  # provenance to image + page
    assert extracted["flag"] is True  # "Trial set" -> surfaced for review


def test_timeline_cli_runs_read_only(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    con = main.open_case_db(out / "lawnlord.duckdb")
    main.apply_schema(con)
    con.close()
    cli.main(["timeline", "--case-dir", str(out)])  # wires up and never writes
