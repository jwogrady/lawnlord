"""Explode = render each filed PDF's pages to PNGs + index documents/pages (F3).

Uses a real 2-page PDF (built with pypdf, a dev dep) so pypdfium2 can render it.
"""

import json

from pypdf import PdfWriter

import lawnlord as main
from lawnlord.transcribe import _row_id

_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "array",
    "items": {"type": "object", "properties": {"caseNumber": {"type": "string"}},
              "required": ["caseNumber"]},
}


def _real_pdf(path, pages=2):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        w.write(f)


def _case(page_count="2"):
    return {
        "caseNumber": "99-00-12345",
        "caseType": "Foreclosure",
        "dateFiled": "01/02/2025",
        "location": "284th",
        "parties": [{"name": "Doe, John", "role": "Defendant", "representation": ["Pro Se"]}],
        "documents": [{"Image": "Petition", "Page Count": page_count, "date": "01/02/2025",
                       "event": "Filed", "file": "files/doc-1.pdf"}],
        "registerOfActions": [{"date": "01/02/2025", "event": "Filed", "section": "events",
                               "documents": ["files/doc-1.pdf"]}],
        "financial": {},
    }


def _build(tmp_path, page_count="2", pdf_pages=2):
    d = tmp_path / "intake"
    (d / "files").mkdir(parents=True)
    (d / "data.json").write_text(json.dumps([_case(page_count)]), encoding="utf-8")
    (d / "schema.json").write_text(json.dumps(_SCHEMA), encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({"capturedAt": "2026-01-01T00:00:00Z"}), encoding="utf-8")
    _real_pdf(d / "files" / "doc-1.pdf", pages=pdf_pages)
    case_dir = tmp_path / "out"
    main.main(["import", str(d), "--case-dir", str(case_dir)])
    return case_dir


def test_explode_renders_pages_and_indexes(tmp_path):
    case_dir = _build(tmp_path, page_count="2", pdf_pages=2)
    main.main(["explode", "--case-dir", str(case_dir)])

    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM pages").fetchone()[0] == 2
        rows = con.execute(
            "SELECT page_number, page_image_path, page_image_sha256 FROM pages ORDER BY page_number"
        ).fetchall()
    finally:
        con.close()

    assert [r[0] for r in rows] == [1, 2]
    for _, rel, sha in rows:
        assert (case_dir / "extracted" / "pages" / rel).is_file()  # PNG written
        assert len(sha) == 64  # hashed


def test_explode_is_deterministic(tmp_path):
    case_dir = _build(tmp_path, pdf_pages=2)
    main.main(["explode", "--case-dir", str(case_dir)])

    def shas():
        con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
        try:
            return con.execute("SELECT page_image_sha256 FROM pages ORDER BY page_number").fetchall()
        finally:
            con.close()

    first = shas()
    main.main(["explode", "--case-dir", str(case_dir)])  # re-run, drop-and-rebuild
    assert shas() == first  # identical PNG bytes → identical hashes


def test_explode_surfaces_page_count_mismatch(tmp_path):
    # Docket declares 3 pages, the PDF has 2 — surfaced, not hidden.
    case_dir = _build(tmp_path, page_count="3", pdf_pages=2)
    intake = main.find_intake_dir(case_dir)
    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    try:
        stats = main.explode_case(con, intake, case_dir / "extracted" / "pages", "2026-01-01T00:00:00Z")
    finally:
        con.close()
    assert stats["pages"] == 2
    assert stats["mismatches"] and stats["mismatches"][0]["declared"] == 3
    assert stats["mismatches"][0]["rendered"] == 2


def test_export_exploded_shape(tmp_path):
    case_dir = _build(tmp_path, page_count="3", pdf_pages=3)
    main.main(["explode", "--case-dir", str(case_dir)])
    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    # Page 1: an AI transcription; page 2: a pdf_text (text-layer) transcription;
    # page 3: untranscribed. The export must surface each page's provenance so the
    # viewer can distinguish ground-truth text from a model's reading.
    pids = [r[0] for r in con.execute("SELECT id FROM pages ORDER BY page_number").fetchall()]
    con.execute(
        "INSERT INTO page_text (id, case_id, page_id, rev, source, text, fidelity, model, created_at) "
        "SELECT ?, case_id, id, 0, 'ai', 'HELLO', 0.9, 'm', 't' FROM pages WHERE id = ?",
        [_row_id(pids[0], "ai", "m", 0), pids[0]],
    )
    con.execute(
        "INSERT INTO page_text (id, case_id, page_id, rev, source, text, fidelity, model, created_at) "
        "SELECT ?, case_id, id, 0, 'pdf_text', 'WORLD', 1.0, NULL, 't' FROM pages WHERE id = ?",
        [_row_id(pids[1], "pdf_text", None, 0), pids[1]],
    )
    try:
        payload = main.export_exploded(con)
    finally:
        con.close()

    assert len(payload["images"]) == 1
    doc = payload["images"][0]["documents"][0]
    pages = doc["pages"]
    assert [p["pageNumber"] for p in pages] == [1, 2, 3]
    # AI page: provenance is source/model/fidelity.
    assert pages[0]["text"] == "HELLO"
    assert pages[0]["source"] == "ai" and pages[0]["model"] == "m" and pages[0]["fidelity"] == 0.9
    # pdf_text page: exact text from the file — no model, fidelity 1.0.
    assert pages[1]["text"] == "WORLD"
    assert pages[1]["source"] == "pdf_text" and pages[1]["model"] is None and pages[1]["fidelity"] == 1.0
    # Untranscribed page: still listed, no text and no provenance.
    assert pages[2]["text"] is None and pages[2]["source"] is None
    assert pages[0]["png"].endswith("p001.png")


def test_explode_does_not_touch_the_mirror(tmp_path):
    case_dir = _build(tmp_path, pdf_pages=1)
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    before = con.execute("SELECT count(*) FROM images").fetchone()[0]
    con.close()
    main.main(["explode", "--case-dir", str(case_dir)])
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    after = con.execute("SELECT count(*) FROM images").fetchone()[0]
    con.close()
    assert before == after == 1  # the mirror is unchanged
