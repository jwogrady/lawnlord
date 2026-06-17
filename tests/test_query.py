"""Read-only query over the case index."""

import json

import fitz
import pytest

import lawnlord as main
from lawnlord import cli


def _pdf(filings, name, lines):
    doc = fitz.open()
    for line in lines:
        doc.new_page().insert_text((72, 72), line)
    doc.save(filings / name)
    doc.close()


def _build_index(tmp_path):
    folder = tmp_path / "ody"
    filings = folder / "filings"
    filings.mkdir(parents=True)
    _pdf(filings, "Petition.pdf", ["ORIGINAL PETITION for foreclosure"])
    _pdf(filings, "Motion.pdf", ["MOTION FOR SUMMARY JUDGMENT"])
    (folder / "case-summary.json").write_text(json.dumps({"caseNumber": "55-00-1"}))
    (folder / "case-history.json").write_text(json.dumps({
        "caseNumber": "55-00-1",
        "parties": [{"role": "Defendant", "name": "Doe, John"}],
        "timeline": [
            {"date": "2025-01-01", "phase": "Pleadings & Service",
             "event": "Original Petition", "party": "Doe, John",
             "files": ["filings/Petition.pdf"]},
            {"date": "2025-03-01", "phase": "Summary Judgment",
             "event": "Motion for Summary Judgment", "files": ["filings/Motion.pdf"]},
        ],
    }))
    (folder / "filings.json").write_text(json.dumps({
        "caseNumber": "55-00-1",
        "otherEventsOnThisCase": [
            {"date": "01/01/2025", "event": "Original Petition", "image": "Petition",
             "pageCount": 1, "file": "filings/Petition.pdf"},
            {"date": "03/01/2025", "event": "Motion for Summary Judgment",
             "image": "Motion", "pageCount": 1, "file": "filings/Motion.pdf"},
        ],
    }))
    case = main.Case.from_intake(folder, case_dir=tmp_path / "out")
    manifest = main.write_corpus(
        case.filings_dir, case.corpus_dir, force=False, manual_boundaries={}, curation={}
    )
    con = main.open_case_db(case.duckdb_path)
    main.apply_schema(con)
    main.ingest_case(con, case, manifest["generatedAt"])
    main.index_corpus(con, case, case.corpus_dir, manifest["generatedAt"])
    con.close()
    return case


def _ro(case):
    return main.open_case_db(case.duckdb_path, read_only=True)


def test_search_text_returns_provenance(tmp_path):
    case = _build_index(tmp_path)
    con = _ro(case)
    rows = main.search_text(con, "summary judgment")
    assert len(rows) == 1
    r = rows[0]
    assert r["image_title"] == "Motion"
    assert r["source_page_number"] == 1
    assert r["citation_display"]  # non-empty citation
    # Petition does not match.
    assert main.search_text(con, "no-such-text") == []


def test_needs_review_documents(tmp_path):
    case = _build_index(tmp_path)
    con = _ro(case)
    rows = main.needs_review_documents(con)
    # Single-page images fall back to a whole-image document (0.5 < 0.9).
    assert len(rows) >= 1
    assert all(r["boundary_confidence"] < 0.9 for r in rows)


def test_images_by_phase_and_event_and_party(tmp_path):
    case = _build_index(tmp_path)
    con = _ro(case)
    phase = main.images_by_phase(con, "Summary Judgment")
    assert [r["image_title"] for r in phase] == ["Motion"]
    event = main.images_by_event(con, "petition")
    assert [r["image_title"] for r in event] == ["Petition"]
    party = main.images_by_party(con, "Doe")
    assert [r["image_title"] for r in party] == ["Petition"]


def test_read_only_open_requires_existing_db(tmp_path):
    with pytest.raises(FileNotFoundError):
        main.open_case_db(tmp_path / "nope.duckdb", read_only=True)


def test_query_cli_runs(tmp_path, capsys):
    case = _build_index(tmp_path)
    cli.main(["query", "--case-dir", str(case.case_dir), "--text", "petition"])
    # CLI smoke: it ran and produced output without raising.
    out = capsys.readouterr().out
    assert "result" in out.lower() or "Petition" in out
