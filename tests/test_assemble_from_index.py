"""Reconstructing the master PDF from the DuckDB data (#32): preserved page
images laid down in docket order, with an invisible searchable text layer burned
in only where a page has no native text."""

import json

import fitz

import lawnlord as main
from lawnlord.assemble import assemble_from_index


def _indexed_case(tmp_path):
    folder = tmp_path / "ody"
    filings = folder / "filings"
    filings.mkdir(parents=True)
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "native page text")
    doc.save(filings / "A.pdf")
    doc.close()
    (folder / "case-summary.json").write_text(json.dumps({"caseNumber": "55-00-7"}))
    (folder / "case-history.json").write_text(json.dumps({
        "caseNumber": "55-00-7",
        "timeline": [{"date": "2025-01-01", "phase": "Pleadings",
                      "event": "Original Petition", "files": ["filings/A.pdf"]}],
    }))
    (folder / "filings.json").write_text(json.dumps({
        "caseNumber": "55-00-7",
        "otherEventsOnThisCase": [
            {"date": "01/01/2025", "event": "Original Petition",
             "image": "A", "pageCount": 1, "file": "filings/A.pdf"}],
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


def test_native_text_page_is_reconstructed_and_searchable(tmp_path):
    case = _indexed_case(tmp_path)
    out = tmp_path / "master.pdf"
    stats = assemble_from_index(case, out)
    assert stats["pages"] == 1
    assert stats["text_lossless"] is True
    assert stats["text_missing"] == 0
    m = fitz.open(out)
    text = m[0].get_text()
    m.close()
    assert "native page text" in text  # the native layer is preserved, searchable


def test_textless_page_gets_a_burned_in_searchable_layer(tmp_path):
    case = _indexed_case(tmp_path)
    # Simulate a scanned page: replace the page image with a text-less PDF and
    # set the chunk's text to OCR-recovered text.
    con = main.open_case_db(case.duckdb_path)
    page_image_path = con.execute("SELECT page_image_path FROM chunks").fetchone()[0]
    con.execute("UPDATE chunks SET text = 'OCR RECOVERED LINE', text_source = 'ocr'")
    con.close()
    textless = fitz.open()
    textless.new_page().draw_rect(fitz.Rect(20, 20, 120, 120))  # image-only, no text
    textless.save(case.corpus_dir / page_image_path)
    textless.close()

    out = tmp_path / "master.pdf"
    stats = assemble_from_index(case, out)
    m = fitz.open(out)
    text = m[0].get_text()
    m.close()
    assert "OCR RECOVERED LINE" in text  # invisible searchable layer burned in
    assert stats["text_lossless"] is True
    assert stats["visual_lossless"] in (True, None)  # the layer is invisible
