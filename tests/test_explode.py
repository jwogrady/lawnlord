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


def _insert_text(con, page_id, source, model, rev, text, fidelity):
    con.execute(
        "INSERT INTO page_text (id, case_id, page_id, rev, source, text, fidelity, model, created_at) "
        "SELECT ?, case_id, id, ?, ?, ?, ?, ?, 't' FROM pages WHERE id = ?",
        [_row_id(page_id, source, model, rev), rev, source, text, fidelity, model, page_id],
    )


def _seed_transcriptions(case_dir):
    """Page 1: pdf_text + 2 ai models (one with a newer rev); page 2: a single
    pdf_text; page 3: untranscribed. Returns the page ids in page order."""
    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    pids = [r[0] for r in con.execute("SELECT id FROM pages ORDER BY page_number").fetchall()]
    # Page 1 — every variation; gemma at rev 0+1 (latest must win), llava + pdf_text.
    _insert_text(con, pids[0], "ai", "gemma", 0, "OLD", 0.5)
    _insert_text(con, pids[0], "ai", "gemma", 1, "GEMMA", 0.8)
    _insert_text(con, pids[0], "ai", "llava", 0, "LLAVA", 0.7)
    _insert_text(con, pids[0], "pdf_text", None, 0, "TRUTH", 1.0)
    # Page 2 — just the text layer.
    _insert_text(con, pids[1], "pdf_text", None, 0, "WORLD", 1.0)
    con.close()
    return pids


def test_export_exploded_shape(tmp_path):
    # The page payload carries every current variation = latest rev per
    # (page_id, source, model), ground-truth first then ai by model name.
    case_dir = _build(tmp_path, page_count="3", pdf_pages=3)
    main.main(["explode", "--case-dir", str(case_dir)])
    _seed_transcriptions(case_dir)
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        payload = main.export_exploded(con)
    finally:
        con.close()

    assert len(payload["images"]) == 1
    doc = payload["images"][0]["documents"][0]
    pages = doc["pages"]
    assert [p["pageNumber"] for p in pages] == [1, 2, 3]
    # The flat text/source/model/fidelity page fields are gone.
    assert "text" not in pages[0] and "source" not in pages[0]

    # Page 1: pdf_text first, then ai by model name; gemma at its latest rev.
    txns = pages[0]["transcriptions"]
    assert [(t["source"], t["model"]) for t in txns] == [
        ("pdf_text", None), ("ai", "gemma"), ("ai", "llava"),
    ]
    # The pdf_text reading is the canonical anchor (ADR-0008): agreement 1.0,
    # empty divergence, alongside the existing variation fields.
    assert txns[0] == {
        "source": "pdf_text", "model": None, "rev": 0,
        "createdAt": "t", "fidelity": 1.0, "text": "TRUTH",
        "agreement": 1.0, "divergence": [],
    }
    assert txns[1]["text"] == "GEMMA" and txns[1]["rev"] == 1 and txns[1]["fidelity"] == 0.8
    assert txns[2]["text"] == "LLAVA"
    # Page 2: a single pdf_text variation.
    assert [(t["source"], t["text"]) for t in pages[1]["transcriptions"]] == [("pdf_text", "WORLD")]
    # Page 3: untranscribed → empty list, page still listed with its image.
    assert pages[2]["transcriptions"] == []
    assert pages[0]["png"].endswith("p001.png")


def test_export_exploded_image_carries_filings(tmp_path):
    # Each image carries the filings (events) that filed it, so the viewer can
    # group case → filing → image without re-deriving (issue #125).
    case_dir = _build(tmp_path, page_count="3", pdf_pages=3)
    main.main(["explode", "--case-dir", str(case_dir)])
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        image = main.export_exploded(con)["images"][0]
    finally:
        con.close()
    assert [(f["event"], f["section"]) for f in image["filings"]] == [("Filed", "events")]
    assert image["filings"][0]["date"] == "01/02/2025"
    assert image["filings"][0]["id"]  # the event id, for filing-level navigation


def test_export_page_scoped(tmp_path):
    case_dir = _build(tmp_path, page_count="3", pdf_pages=3)
    main.main(["explode", "--case-dir", str(case_dir)])
    pids = _seed_transcriptions(case_dir)
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        page1 = main.export_page(con, pids[0])
        page3 = main.export_page(con, pids[2])
        missing = main.export_page(con, "nope")
    finally:
        con.close()
    assert page1["page"]["pageNumber"] == 1
    assert [t["model"] for t in page1["page"]["transcriptions"]] == [None, "gemma", "llava"]
    assert page3["page"]["transcriptions"] == []
    assert missing == {}


def test_export_document_scoped(tmp_path):
    case_dir = _build(tmp_path, page_count="3", pdf_pages=3)
    main.main(["explode", "--case-dir", str(case_dir)])
    _seed_transcriptions(case_dir)
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        doc_id = con.execute("SELECT id FROM documents LIMIT 1").fetchone()[0]
        out = main.export_document(con, doc_id)
        missing = main.export_document(con, "nope")
    finally:
        con.close()
    assert [p["pageNumber"] for p in out["document"]["pages"]] == [1, 2, 3]
    assert "image_id" not in out["document"]
    assert missing == {}


def test_export_image_scoped(tmp_path):
    case_dir = _build(tmp_path, page_count="3", pdf_pages=3)
    main.main(["explode", "--case-dir", str(case_dir)])
    _seed_transcriptions(case_dir)
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        image_id = con.execute("SELECT id FROM images LIMIT 1").fetchone()[0]
        out = main.export_image(con, image_id)
        missing = main.export_image(con, "nope")
    finally:
        con.close()
    assert out["image"]["imageId"] == image_id
    assert out["image"]["documents"][0]["pages"][0]["pageNumber"] == 1
    assert missing == {}


def test_export_filing_scoped(tmp_path):
    # A filing is a grouping over image_events: it returns the images linked to
    # that event, each fully exploded.
    case_dir = _build(tmp_path, page_count="3", pdf_pages=3)
    main.main(["explode", "--case-dir", str(case_dir)])
    _seed_transcriptions(case_dir)
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        event_id = con.execute(
            "SELECT event_id FROM image_events LIMIT 1"
        ).fetchone()[0]
        out = main.export_filing(con, event_id)
        missing = main.export_filing(con, "nope")
    finally:
        con.close()
    assert out["filing"]["id"] == event_id
    assert len(out["images"]) == 1
    assert out["images"][0]["documents"][0]["pages"][0]["pageNumber"] == 1
    assert missing == {}


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
