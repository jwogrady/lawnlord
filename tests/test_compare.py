"""The compare emitter: render actual vs reconstructed pages + lawnlord's score
into the artifact the web reviewer reads."""

import json

import fitz

import lawnlord as main
from lawnlord.compare import emit_compare


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
        # both renders exist on disk where the JSON points (minus the leading /)
        assert (out / p["actual"].lstrip("/")).exists()
        assert (out / p["reconstructed"].lstrip("/")).exists()
        assert 0.0 <= p["score"] <= 1.0
        assert p["note"]
    # native text + declared(2)==actual(2) + docketed -> full confidence
    assert data["pages"][0]["score"] == 1.0
