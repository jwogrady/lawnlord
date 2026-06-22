"""Explode = render each filed PDF's pages to PNGs + index documents/pages (F3).

Uses a real 2-page PDF (built with pypdf, a dev dep) so pypdfium2 can render it.
"""

import json

from pypdf import PdfWriter

import lawnlord as main

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
