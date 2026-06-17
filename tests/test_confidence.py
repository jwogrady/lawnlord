"""Two-sided confidence (#33): each page scored against the Odyssey metadata
(declared vs actual page count, docketed) and the source PDF (text extracted),
persisted to chunks/documents/cases and folded into `query --needs-review`."""

import json

import fitz

import lawnlord as main
from lawnlord.query import needs_review_pages


def _pdf(filings, name, pages):
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"{name} page {i + 1}")
    doc.save(filings / name)
    doc.close()


def _indexed(tmp_path):
    folder = tmp_path / "ody"
    filings = folder / "filings"
    filings.mkdir(parents=True)
    _pdf(filings, "Petition.pdf", 2)  # declared 2, actual 2 -> clean
    _pdf(filings, "Motion.pdf", 1)  # declared 99, actual 1 -> mismatch
    (folder / "case-summary.json").write_text(json.dumps({"caseNumber": "55-00-3"}))
    (folder / "case-history.json").write_text(json.dumps({
        "caseNumber": "55-00-3",
        "timeline": [
            {"date": "2025-01-01", "phase": "Pleadings", "event": "Original Petition",
             "files": ["filings/Petition.pdf"]},
            {"date": "2025-03-01", "phase": "Summary Judgment",
             "event": "Motion for Summary Judgment", "files": ["filings/Motion.pdf"]},
        ],
    }))
    (folder / "filings.json").write_text(json.dumps({
        "caseNumber": "55-00-3",
        "otherEventsOnThisCase": [
            {"date": "01/01/2025", "event": "Original Petition", "image": "Petition",
             "pageCount": 2, "file": "filings/Petition.pdf"},
            {"date": "03/01/2025", "event": "Motion for Summary Judgment",
             "image": "Motion", "pageCount": 99, "file": "filings/Motion.pdf"},
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
    return case, con, stats


def test_clean_pages_are_ai_accessible_mismatch_flagged(tmp_path):
    case, con, stats = _indexed(tmp_path)
    # Petition (declared 2 == actual 2, docketed, text) -> full confidence.
    petition = con.execute(
        "SELECT c.confidence, c.ai_accessible, c.needs_review FROM chunks c "
        "JOIN images i ON i.id = c.image_id WHERE i.filename = 'Petition.pdf' LIMIT 1"
    ).fetchone()
    assert petition == (1.0, True, False)
    # Motion (declared 99 != actual 1) -> structure fails, flagged for review.
    motion = con.execute(
        "SELECT c.confidence, c.ai_accessible, c.needs_review FROM chunks c "
        "JOIN images i ON i.id = c.image_id WHERE i.filename = 'Motion.pdf' LIMIT 1"
    ).fetchone()
    assert motion[1] is False and motion[2] is True and motion[0] < 0.8
    con.close()


def test_confidence_rolls_up_to_documents_and_case(tmp_path):
    case, con, stats = _indexed(tmp_path)
    assert stats["scored_pages"] == 3 and stats["ai_accessible"] == 2
    case_conf = con.execute("SELECT confidence FROM cases").fetchone()[0]
    # Two clean pages at 1.0 + one mismatch page at 0.5 -> mean 5/6.
    assert abs(case_conf - (2 * 1.0 + 0.5) / 3) < 1e-6
    doc_confs = con.execute("SELECT confidence FROM documents ORDER BY confidence").fetchall()
    assert doc_confs[0][0] < 0.8  # the Motion document
    con.close()


def test_needs_review_folds_in_low_confidence_pages(tmp_path):
    case, con, stats = _indexed(tmp_path)
    flagged = needs_review_pages(con)
    con.close()
    assert any(p["confidence"] < 0.8 for p in flagged)
    assert all(p["confidence"] < 0.8 for p in flagged)  # only sub-threshold pages
