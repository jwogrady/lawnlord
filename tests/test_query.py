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


# --- F5b: BM25 full-text search, best-effort with LIKE fallback -------------


def _fts_available():
    import duckdb

    from lawnlord import db
    return db.load_fts(duckdb.connect())


def _ranking_index(tmp_path):
    """Three pages with differing relevance to 'summary judgment'."""
    folder = tmp_path / "ody"
    filings = folder / "filings"
    filings.mkdir(parents=True)
    _pdf(filings, "High.pdf", ["summary judgment summary judgment summary judgment"])
    _pdf(filings, "Low.pdf", ["a passing mention of summary judgment here"])
    _pdf(filings, "None.pdf", ["unrelated original petition for foreclosure"])
    (folder / "case-summary.json").write_text(json.dumps({"caseNumber": "55-00-2"}))
    (folder / "case-history.json").write_text(json.dumps({"caseNumber": "55-00-2"}))
    (folder / "filings.json").write_text(json.dumps({
        "caseNumber": "55-00-2",
        "otherEventsOnThisCase": [
            {"event": "E", "image": n[:-4], "pageCount": 1, "file": f"filings/{n}"}
            for n in ("High.pdf", "Low.pdf", "None.pdf")
        ],
    }))
    case = main.Case.from_intake(folder, case_dir=tmp_path / "out")
    manifest = main.write_corpus(
        case.filings_dir, case.corpus_dir, force=False, manual_boundaries={}, curation={}
    )
    con = main.open_case_db(case.duckdb_path)
    main.apply_schema(con)
    main.ingest_case(con, case, manifest["generatedAt"])
    stats = main.index_corpus(con, case, case.corpus_dir, manifest["generatedAt"])
    con.close()
    return case, stats


def test_index_reports_fts_status(tmp_path):
    _, stats = _ranking_index(tmp_path)
    assert isinstance(stats["fts"], bool)


def test_bm25_ranks_by_relevance(tmp_path):
    if not _fts_available():
        pytest.skip("FTS extension unavailable in this environment")
    case, stats = _ranking_index(tmp_path)
    assert stats["fts"] is True
    con = _ro(case)
    rows = main.search_text(con, "summary judgment")
    titles = [r["image_title"] for r in rows]
    assert titles[:2] == ["High", "Low"]  # ranked; the unrelated page is absent
    assert "None" not in titles
    assert all("score" in r for r in rows)  # BM25 path used


def test_search_falls_back_to_substring_without_fts(tmp_path, monkeypatch):
    # Force FTS unavailable: search still works via the substring scan.
    case = _build_index(tmp_path)
    con = _ro(case)
    monkeypatch.setattr("lawnlord.db.load_fts", lambda con: False)
    rows = main.search_text(con, "summary judgment")
    assert len(rows) == 1
    assert rows[0]["image_title"] == "Motion"
    assert "score" not in rows[0]  # LIKE path, no BM25 score column
