"""The compare emitter: render actual vs reconstructed pages + lawnlord's score
into the artifact the web reviewer reads."""

import json

import fitz

import lawnlord as main
from lawnlord.compare import _reconcile, emit_compare


def _intake(tmp_path):
    folder = tmp_path / "ody"
    filings = folder / "filings"
    filings.mkdir(parents=True)
    doc = fitz.open()
    for i in range(2):
        doc.new_page().insert_text((72, 72), f"Petition page {i + 1}")
    doc.save(filings / "Petition.pdf")
    doc.close()
    (folder / "case-summary.json").write_text(json.dumps({"caseNumber": "55-00-8"}))
    (folder / "case-history.json").write_text(json.dumps({
        "caseNumber": "55-00-8",
        "timeline": [{"date": "2025-01-01", "phase": "Pleadings",
                      "event": "Original Petition", "files": ["filings/Petition.pdf"]}],
    }))
    (folder / "filings.json").write_text(json.dumps({
        "caseNumber": "55-00-8",
        "otherEventsOnThisCase": [
            {"date": "01/01/2025", "event": "Original Petition", "image": "Petition",
             "pageCount": 2, "file": "filings/Petition.pdf"}],
    }))
    return folder


def test_emit_compare_renders_pages_scores_and_json(tmp_path):
    case = main.Case.from_intake(_intake(tmp_path), case_dir=tmp_path / "out")
    out = tmp_path / "compare"
    stats = emit_compare(case, out, dpi=72)

    assert stats["pages"] == 2
    data = json.loads((out / "compare.json").read_text())
    assert data["case"] == "55-00-8" and len(data["pages"]) == 2
    for p in data["pages"]:
        # the filed page is rendered to an image; the right side is our text
        assert (out / p["actual"].lstrip("/")).exists()
        assert "Petition page" in p["text"]  # our textual representation
        assert p["masterPage"] >= 1  # links to the assembled reconstruction PDF
        assert 0.0 <= p["score"] <= 1.0
        assert p["note"]
        # the court's structure: case -> filing (submission event) -> image
        assert p["filing"]["title"] and p["image"].endswith(".pdf")
        assert p["declaredPages"] == 2 and p["page"] in (1, 2)
        # "document" is additive (a part/exhibit) — present or null, never the root
        assert p["document"] is None or "title" in p["document"]
    # output reconciles with the manifest: 2 rendered == 2 declared, no drops
    assert data["integrity"]["ok"] is True and not data["integrity"]["errors"]
    assert data["integrity"]["renderedPages"] == 2
    # the Original layer is emitted verbatim: the court's register of actions
    man = json.loads((out / "manifest.json").read_text())
    assert man["case"] == "55-00-8" and man["registerOfActions"]
    assert any(
        e["filing"] and e["filing"]["declaredPages"] == 2
        for e in man["registerOfActions"]
    )
    # native text + declared(2)==actual(2) + docketed -> full confidence
    assert data["pages"][0]["score"] == 1.0


def test_reconcile_errors_on_a_dropped_page():
    # We hold 3 source pages but only rendered 2 -> a real drop, hard error.
    integ = _reconcile({"a.pdf": {1, 2}}, {"a.pdf": 3}, {"a.pdf": 3}, 2)
    assert integ["ok"] is False
    assert any("rendered 2 of 3" in e for e in integ["errors"])


def test_reconcile_flags_docket_vs_file_mismatch():
    # All file pages rendered, but the docket's declared count disagrees -> a
    # finding (flag), not a tool failure.
    integ = _reconcile({"a.pdf": {1, 2, 3}}, {"a.pdf": 5}, {"a.pdf": 3}, 3)
    assert integ["ok"] is True and not integ["errors"]
    assert any("docket declares 5" in f for f in integ["flags"])
