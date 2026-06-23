"""Divergence, agreement & aggregate metrics in the export layer (ADR-0008).

Confidence is defined once, here, so every consumer agrees: each page's readings
are compared to a canonical anchor (pdf_text when present, else the cross-model
consensus medoid), each carrying an agreement (0.0–1.0) and a divergence (changed
token spans); image/case rollups give coverage, mean agreement, per-model
fidelity, and a flagged-page worklist. Built by direct DB inserts — no network.
"""

import json

import lawnlord as main
from lawnlord import export

_T = "t0"  # deterministic created_at (never wall-clock)


def _con(tmp_path):
    con = main.open_case_db(tmp_path / "lawnlord.duckdb")
    main.apply_schema(con)
    con.execute("INSERT INTO cases (id, created_at) VALUES ('C', ?)", [_T])
    return con


def _image(con, image_id):
    con.execute(
        "INSERT INTO images (id, case_id, title, filing_date, sha256_hash, created_at) "
        "VALUES (?, 'C', ?, '01/01/2025', 'h', ?)",
        [image_id, image_id, _T],
    )
    con.execute(
        "INSERT INTO documents (id, case_id, image_id, title, page_count, created_at) "
        "VALUES (?, 'C', ?, ?, 1, ?)",
        [f"doc_{image_id}", image_id, image_id, _T],
    )


def _page(con, page_id, image_id):
    con.execute(
        "INSERT INTO pages (id, case_id, image_id, document_id, page_number, "
        "page_image_path, created_at) VALUES (?, 'C', ?, ?, 1, ?, ?)",
        [page_id, image_id, f"doc_{image_id}", f"{page_id}.png", _T],
    )


def _text(con, page_id, source, model, text, fidelity, rev=0):
    rid = f"pt_{page_id}_{source}_{model or 'x'}_{rev}"
    con.execute(
        "INSERT INTO page_text (id, case_id, page_id, rev, source, text, fidelity, "
        "model, created_at) VALUES (?, 'C', ?, ?, ?, ?, ?, ?, ?)",
        [rid, page_id, rev, source, text, fidelity, model, _T],
    )


# --- (a) anchor = pdf_text when present -------------------------------------


def test_anchor_is_pdf_text_when_present(tmp_path):
    con = _con(tmp_path)
    _image(con, "img1")
    _page(con, "p1", "img1")
    # pdf_text is the anchor even though an ai reading also exists.
    _text(con, "p1", "pdf_text", None, "the quick brown fox", 1.0)
    _text(con, "p1", "ai", "modelA", "the quick brown dog", 0.9)

    page = export.export_page(con, "p1")["page"]
    con.close()

    by_key = {(t["source"], t["model"]): t for t in page["transcriptions"]}
    anchor = by_key[("pdf_text", None)]
    other = by_key[("ai", "modelA")]
    assert anchor["agreement"] == 1.0
    assert anchor["divergence"] == []
    # One token differs out of four -> agreement < 1, with a replace span.
    assert other["agreement"] < 1.0
    assert any(s["op"] == "replace" for s in other["divergence"])
    span = next(s for s in other["divergence"] if s["op"] == "replace")
    assert span["anchor"]["tokens"] == ["fox"]
    assert span["variation"]["tokens"] == ["dog"]


# --- (b) anchor = consensus medoid when no pdf_text -------------------------


def test_anchor_is_consensus_medoid_without_pdf_text(tmp_path):
    con = _con(tmp_path)
    _image(con, "img1")
    _page(con, "p1", "img1")
    # Three ai readings: B and C agree; A is the outlier. The medoid (highest
    # mean pairwise agreement) is B or C; ties broken by model name -> modelB.
    _text(con, "p1", "ai", "modelA", "alpha beta gamma delta", 0.9)
    _text(con, "p1", "ai", "modelB", "alpha beta gamma epsilon", 0.9)
    _text(con, "p1", "ai", "modelC", "alpha beta gamma epsilon", 0.9)

    page = export.export_page(con, "p1")["page"]
    con.close()

    by_model = {t["model"]: t for t in page["transcriptions"]}
    assert by_model["modelB"]["agreement"] == 1.0  # anchor
    assert by_model["modelB"]["divergence"] == []
    assert by_model["modelC"]["agreement"] == 1.0  # identical text to anchor
    assert by_model["modelA"]["agreement"] < 1.0  # the outlier diverges
    # The tie-break is deterministic at the source: B and C share the top mean
    # pairwise agreement, and the medoid picks the first in the model-sorted list
    # (modelB). Asserted directly because B and C have identical text and so are
    # otherwise indistinguishable at the public API.
    sorted_vars = sorted(
        page["transcriptions"],
        key=lambda t: (t["source"] != "pdf_text", t["source"], t["model"] or ""),
    )
    assert sorted_vars[export._anchor_index(sorted_vars)]["model"] == "modelB"


def test_anchor_is_unique_medoid_without_pdf_text(tmp_path):
    con = _con(tmp_path)
    _image(con, "img1")
    _page(con, "p1", "img1")
    # No ties: modelB is the central reading — closest to both A and C — so it is
    # the unique medoid regardless of tie-break. A and C diverge from the anchor.
    _text(con, "p1", "ai", "modelA", "one two three four five", 0.9)
    _text(con, "p1", "ai", "modelB", "one two three four six", 0.9)
    _text(con, "p1", "ai", "modelC", "one two zzz qqq six", 0.9)

    page = export.export_page(con, "p1")["page"]
    con.close()
    by_model = {t["model"]: t for t in page["transcriptions"]}
    assert by_model["modelB"]["agreement"] == 1.0  # the unique medoid anchor
    assert by_model["modelB"]["divergence"] == []
    assert by_model["modelA"]["agreement"] < 1.0
    assert by_model["modelC"]["agreement"] < 1.0


# --- (c) agreement: 1.0 for anchor, <1 for a divergent reading --------------


def test_single_ai_reading_is_its_own_anchor(tmp_path):
    con = _con(tmp_path)
    _image(con, "img1")
    _page(con, "p1", "img1")
    _text(con, "p1", "ai", "modelA", "lonely reading", 0.95)

    page = export.export_page(con, "p1")["page"]
    con.close()
    only = page["transcriptions"][0]
    assert only["agreement"] == 1.0 and only["divergence"] == []


def test_divergence_includes_insert_and_delete(tmp_path):
    con = _con(tmp_path)
    _image(con, "img1")
    _page(con, "p1", "img1")
    _text(con, "p1", "pdf_text", None, "one two three", 1.0)
    _text(con, "p1", "ai", "modelA", "one two three four", 0.9)  # insert
    _text(con, "p1", "ai", "modelB", "one three", 0.9)  # delete

    page = export.export_page(con, "p1")["page"]
    con.close()
    by_model = {t["model"]: t for t in page["transcriptions"]}
    assert any(s["op"] == "insert" for s in by_model["modelA"]["divergence"])
    assert any(s["op"] == "delete" for s in by_model["modelB"]["divergence"])


# --- (d) aggregate metrics: coverage + flagged-page detection ---------------


def test_metrics_coverage_and_flagged_pages(tmp_path):
    con = _con(tmp_path)
    _image(con, "img1")
    # Both pages carry the full variation set {pdf_text, modelA} -> full coverage.
    # Page 1: readings agree, healthy fidelity -> not flagged.
    _page(con, "p1", "img1")
    _text(con, "p1", "pdf_text", None, "clean page text here", 1.0)
    _text(con, "p1", "ai", "modelA", "clean page text here", 0.95)
    # Page 2: ai diverges hard from the pdf_text anchor (low agreement) and has
    #         low fidelity -> flagged.
    _page(con, "p2", "img1")
    _text(con, "p2", "pdf_text", None, "alpha beta gamma delta epsilon", 1.0)
    _text(con, "p2", "ai", "modelA", "totally different words entirely now", 0.5)

    metrics = export.export_metrics(con)
    con.close()

    case = metrics["case"]
    # Expected variation set = union of (pdf_text), (ai,modelA) = 2.
    # 2 pages x 2 = 4 cells expected; present = 4 -> full coverage.
    assert case["coverage"]["expected"] == 4
    assert case["coverage"]["present"] == 4
    assert case["coverage"]["fraction"] == 1.0

    # p1 is clean; p2 is flagged (low agreement + low fidelity).
    assert case["flaggedPages"] == ["p2"]
    assert case["flaggedPageCount"] == 1

    # Per-model fidelity distribution: modelA on both pages (0.95 and 0.5).
    fid = case["fidelityByModel"]
    assert fid["modelA"]["count"] == 2
    assert fid["modelA"]["min"] == 0.5 and fid["modelA"]["max"] == 0.95

    # Image rollup mirrors the case rollup for a single-image case.
    assert metrics["images"][0]["imageId"] == "img1"
    assert metrics["images"][0]["flaggedPages"] == ["p2"]


def test_missing_expected_variation_flags_page(tmp_path):
    con = _con(tmp_path)
    _image(con, "img1")
    # p1 has both readings; p2 is missing modelA that p1 establishes as expected.
    _page(con, "p1", "img1")
    _text(con, "p1", "pdf_text", None, "same words here", 1.0)
    _text(con, "p1", "ai", "modelA", "same words here", 0.95)
    _page(con, "p2", "img1")
    _text(con, "p2", "pdf_text", None, "same words here", 1.0)

    case = export.export_metrics(con)["case"]
    con.close()
    # p2 is flagged purely on a missing expected variation; coverage drops below 1.
    assert case["coverage"]["fraction"] < 1.0
    assert case["flaggedPages"] == ["p2"]


def test_metrics_scoped_to_one_image(tmp_path):
    con = _con(tmp_path)
    _image(con, "img1")
    _page(con, "p1", "img1")
    _text(con, "p1", "ai", "modelA", "img one page", 0.9)
    _image(con, "img2")
    _page(con, "p2", "img2")
    _text(con, "p2", "ai", "modelA", "img two page", 0.9)

    scoped = export.export_metrics(con, image_id="img2")
    con.close()
    assert scoped["case"]["pages"] == 1
    assert [i["imageId"] for i in scoped["images"]] == ["img2"]
    assert scoped["images"][0]["pages"] == 1


def test_metrics_cli_emits_json(tmp_path, capsys):
    con = _con(tmp_path)
    _image(con, "img1")
    _page(con, "p1", "img1")
    _text(con, "p1", "ai", "modelA", "some text", 0.9)
    con.close()
    main.main(["export-metrics", "--case-dir", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)
    assert "case" in payload and "images" in payload
    assert payload["case"]["pages"] == 1
