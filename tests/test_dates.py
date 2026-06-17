"""Date-fact extraction (#36): dates found in page text, fed to the index as
facts (needs_review), never as interpretations."""

import json

import fitz

import lawnlord as main
from lawnlord.dates import extract_dates


def test_extract_dates_finds_iso_numeric_and_longform():
    text = "Response due 01/15/2025. Hearing set for January 5, 2026. Filed 2025-09-05."
    facts = extract_dates(text)
    dates = [f["date"] for f in facts]
    assert "2025-01-15" in dates  # numeric M/D/Y, normalized to ISO
    assert "2026-01-05" in dates  # long-form
    assert "2025-09-05" in dates  # already ISO
    # ordered by appearance, each with a surrounding snippet and a confidence
    assert facts[0]["spanStart"] < facts[1]["spanStart"] < facts[2]["spanStart"]
    assert "Response due" in facts[0]["snippet"]
    assert all(0.0 <= f["confidence"] <= 1.0 for f in facts)


def test_extract_dates_empty_and_no_dates():
    assert extract_dates("") == []
    assert extract_dates("No dates here, only words.") == []


def _intake_with_dated_page(tmp_path):
    folder = tmp_path / "ody"
    filings = folder / "filings"
    filings.mkdir(parents=True)
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Docket Control Order. Trial set for 03/10/2026.")
    doc.save(filings / "Order.pdf")
    doc.close()
    (folder / "case-summary.json").write_text(json.dumps({"caseNumber": "55-00-2"}))
    (folder / "case-history.json").write_text(json.dumps({
        "caseNumber": "55-00-2",
        "timeline": [{"date": "2025-01-01", "phase": "Pretrial",
                      "event": "Docket Control Order", "files": ["filings/Order.pdf"]}],
    }))
    (folder / "filings.json").write_text(json.dumps({
        "caseNumber": "55-00-2",
        "otherEventsOnThisCase": [
            {"date": "01/01/2025", "event": "Docket Control Order",
             "image": "Order", "pageCount": 1, "file": "filings/Order.pdf"}],
    }))
    return folder


def test_index_extracts_dates_as_facts(tmp_path):
    folder = _intake_with_dated_page(tmp_path)
    case = main.Case.from_intake(folder, case_dir=tmp_path / "out")
    manifest = main.write_corpus(
        case.filings_dir, case.corpus_dir, force=False, manual_boundaries={}, curation={}
    )
    con = main.open_case_db(case.duckdb_path)
    main.apply_schema(con)
    main.ingest_case(con, case, manifest["generatedAt"])
    stats = main.index_corpus(con, case, case.corpus_dir, manifest["generatedAt"])

    assert stats["dates"] >= 1
    row = con.execute(
        "SELECT date, source, needs_review, source_page_number, snippet "
        "FROM extracted_dates WHERE date = '2026-03-10'"
    ).fetchone()
    assert row is not None
    date, source, needs_review, spn, snippet = row
    assert source == "extracted"  # a fact from the record, not human-entered
    assert needs_review is True  # never asserted as truth without a human
    assert spn == 1
    assert "Trial set" in snippet
