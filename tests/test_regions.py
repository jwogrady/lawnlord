"""Spatial-anchor layer (ADR-0009): boxes per text span from PDF geometry.

Pure helpers (token offsets, coordinate normalization, deterministic ids) plus
the capture step, exercised against a real single-line text PDF so pypdfium2
returns actual glyph boxes. No network.
"""

import json

import lawnlord as main
from lawnlord.regions import (
    _region_id,
    capture_pdf_regions,
    extract_pdf_charboxes,
    normalize_rect,
    span_bbox_points,
    token_char_offsets,
)
from lawnlord.transcribe import _row_id

_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "array",
    "items": {"type": "object", "properties": {"caseNumber": {"type": "string"}},
              "required": ["caseNumber"]},
}


def _text_pdf(path, text="The quick brown fox jumps"):
    """A minimal single-page PDF carrying `text` as one line of real glyphs, so
    pypdfium2's textpage returns boxes. `text` must avoid '(' ')' '\\'."""
    content = b"BT /F1 24 Tf 72 700 Td (" + text.encode("ascii") + b") Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n%s\nendobj\n" % (i, o)
    xref = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        pdf += b"%010d 00000 n \n" % off
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (
        len(objs) + 1, xref)
    path.write_bytes(pdf)


def _case():
    return {
        "caseNumber": "99-00-12345",
        "caseType": "Foreclosure",
        "dateFiled": "01/02/2025",
        "parties": [{"name": "Doe, John", "role": "Defendant", "representation": ["Pro Se"]}],
        "documents": [{"Image": "Petition", "Page Count": "1", "date": "01/02/2025",
                       "event": "Filed", "file": "files/doc-1.pdf"}],
        "registerOfActions": [{"date": "01/02/2025", "event": "Filed", "section": "events",
                               "documents": ["files/doc-1.pdf"]}],
        "financial": {},
    }


def _build(tmp_path, text="The quick brown fox jumps"):
    d = tmp_path / "intake"
    (d / "files").mkdir(parents=True)
    (d / "data.json").write_text(json.dumps([_case()]), encoding="utf-8")
    (d / "schema.json").write_text(json.dumps(_SCHEMA), encoding="utf-8")
    (d / "manifest.json").write_text(
        json.dumps({"capturedAt": "2026-01-01T00:00:00Z"}), encoding="utf-8")
    _text_pdf(d / "files" / "doc-1.pdf", text)
    case_dir = tmp_path / "out"
    main.main(["import", str(d), "--case-dir", str(case_dir)])
    main.main(["explode", "--case-dir", str(case_dir)])
    return case_dir


def _seed_pdf_text(case_dir, text):
    """Insert a `pdf_text` page_text row on the (single) page with the given text,
    returning (page_id, anchor_id). Mirrors how transcribe stores the text layer."""
    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    page_id = con.execute("SELECT id FROM pages ORDER BY page_number LIMIT 1").fetchone()[0]
    anchor_id = _row_id(page_id, "pdf_text", None, 0)
    con.execute(
        "INSERT INTO page_text (id, case_id, page_id, rev, source, text, fidelity, "
        "model, created_at) SELECT ?, case_id, id, 0, 'pdf_text', ?, 1.0, NULL, 't' "
        "FROM pages WHERE id = ?",
        [anchor_id, text, page_id],
    )
    con.close()
    return page_id, anchor_id


# --- (a) pure helpers --------------------------------------------------------

def test_token_char_offsets_match_split():
    for text in [
        "one two three",
        "  leading and trailing  ",
        "tabs\tand\nnewlines here",
        "multiple    spaces   between",
        "single",
        "",
        "   ",
    ]:
        offs = token_char_offsets(text)
        # Same tokens, same order, as str.split() — and the offsets carve them out.
        assert [text[s:e] for s, e in offs] == text.split()
        # Repeated tokens map to distinct, increasing spans (no naive re-find).
        assert all(s < e for s, e in offs)
        assert all(offs[i][1] <= offs[i + 1][0] for i in range(len(offs) - 1))


def test_normalize_rect_flips_y_and_scales():
    # points bottom-left (l,b,r,t) -> normalized top-left (x0,y0,x1,y1).
    assert normalize_rect(10, 20, 30, 40, 100, 200) == (0.1, 0.8, 0.3, 0.9)


def test_span_bbox_points_unions_glyphs():
    boxes = [(10, 0, 20, 10), (20, 1, 35, 11), (35, 0, 40, 9)]
    assert span_bbox_points(boxes, 0, 3) == (10, 0, 40, 11)
    assert span_bbox_points(boxes, 1, 2) == (20, 1, 35, 11)
    assert span_bbox_points(boxes, 2, 2) is None  # empty range


def test_region_id_is_deterministic_and_ignores_coordinates():
    a = _region_id("page_text", "pt_abc", 3)
    assert a == _region_id("page_text", "pt_abc", 3)  # stable
    assert a != _region_id("page_text", "pt_abc", 4)  # span index matters
    assert a != _region_id("entity", "pt_abc", 3)  # anchor kind matters
    assert a.startswith("pr_")


# --- (b) PDF geometry extraction --------------------------------------------

def test_extract_pdf_charboxes_aligns_with_text(tmp_path):
    pdf = tmp_path / "t.pdf"
    _text_pdf(pdf, "Hello World")
    pages = extract_pdf_charboxes(pdf)
    assert len(pages) == 1
    page = pages[0]
    assert page["text"] == "Hello World"
    # One glyph box per character (the alignment the capture step relies on).
    assert len(page["charboxes"]) == len(page["text"])
    assert page["size"] == (612.0, 792.0)


# --- (c) capture: one normalized region per token, deterministic & additive --

def test_capture_pdf_regions_one_per_token(tmp_path):
    case_dir = _build(tmp_path, "The quick brown fox jumps")
    # Anchor text must equal the PDF's own text layer (what transcribe would store).
    pdf = main.find_intake_dir(case_dir) / "files" / "doc-1.pdf"
    pdf_text = extract_pdf_charboxes(pdf)[0]["text"]
    page_id, anchor_id = _seed_pdf_text(case_dir, pdf_text)

    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    stats = capture_pdf_regions(con, main.find_intake_dir(case_dir), "2026-01-01T00:00:00Z")
    rows = con.execute(
        "SELECT span_index, char_start, char_end, x0, y0, x1, y1, anchor_id, "
        "anchor_kind, origin, confidence FROM page_regions ORDER BY span_index"
    ).fetchall()
    con.close()

    tokens = pdf_text.split()
    assert stats["regions"] == len(tokens)
    assert stats["pages_with_geometry"] == 1
    assert [r[0] for r in rows] == list(range(len(tokens)))  # span_index 0..n-1
    for (span_index, cs, ce, x0, y0, x1, y1, a_id, kind, origin, conf), tok in zip(rows, tokens):
        assert pdf_text[cs:ce] == tok  # char range carves the token
        assert a_id == anchor_id and kind == "page_text"
        assert origin == "pdf_text" and conf == 1.0
        assert 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0  # normalized, ordered


def test_capture_pdf_regions_is_idempotent(tmp_path):
    case_dir = _build(tmp_path, "alpha beta gamma")
    pdf_text = extract_pdf_charboxes(main.find_intake_dir(case_dir) / "files" / "doc-1.pdf")[0]["text"]
    _seed_pdf_text(case_dir, pdf_text)

    def run():
        con = main.open_case_db(case_dir / "lawnlord.duckdb")
        main.apply_schema(con)
        capture_pdf_regions(con, main.find_intake_dir(case_dir), "2026-01-01T00:00:00Z")
        ids = [r[0] for r in con.execute("SELECT id FROM page_regions ORDER BY id").fetchall()]
        con.close()
        return ids

    first = run()
    assert first and run() == first  # re-running rebuilds identical rows/ids


def test_capture_never_fabricates_when_text_mismatches(tmp_path):
    # A pdf_text row whose text does NOT match the PDF's glyphs must yield no
    # regions — geometry is never invented to fit a divergent anchor.
    case_dir = _build(tmp_path, "real glyphs on the page")
    _seed_pdf_text(case_dir, "totally different stored text")

    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    stats = capture_pdf_regions(con, main.find_intake_dir(case_dir), "2026-01-01T00:00:00Z")
    n = con.execute("SELECT count(*) FROM page_regions").fetchone()[0]
    con.close()
    assert n == 0
    assert len(stats["skipped_mismatch"]) == 1


# --- (d) read-only export the renderer consumes ------------------------------

def test_export_regions_shape(tmp_path):
    case_dir = _build(tmp_path, "one two")
    pdf_text = extract_pdf_charboxes(main.find_intake_dir(case_dir) / "files" / "doc-1.pdf")[0]["text"]
    page_id, anchor_id = _seed_pdf_text(case_dir, pdf_text)
    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    capture_pdf_regions(con, main.find_intake_dir(case_dir), "2026-01-01T00:00:00Z")
    con.close()

    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    out = main.export_regions(con, page_id=page_id)
    missing = main.export_regions(con, page_id="nope")
    con.close()
    assert out["pageId"] == page_id
    assert len(out["regions"]) == len(pdf_text.split())
    r = out["regions"][0]
    assert r["anchorKind"] == "page_text" and r["anchorId"] == anchor_id
    assert set(["id", "spanIndex", "charStart", "charEnd", "x0", "y0", "x1", "y1",
                "origin", "confidence"]).issubset(r)
    assert all(0.0 <= reg["x0"] <= 1.0 and 0.0 <= reg["y1"] <= 1.0 for reg in out["regions"])
    assert missing["regions"] == []
