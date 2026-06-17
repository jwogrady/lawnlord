"""combine: compile the ody + txe portal views into one combo provider intake."""

import json

import fitz

import lawnlord as main
from lawnlord.combine import combine


def _ody(tmp_path):
    folder = tmp_path / "ody"
    filings = folder / "filings"
    filings.mkdir(parents=True)
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Petition page 1")
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
             "pageCount": 1, "file": "filings/Petition.pdf"}],
    }))
    return folder


def _txe(tmp_path):
    folder = tmp_path / "txe"
    folder.mkdir()
    (folder / "meta.json").write_text(json.dumps({"caseNumber": "55-00-8", "parties": []}))
    return folder


def test_combine_stages_combo_folder(tmp_path):
    out = tmp_path / "combo"
    stats = combine(_ody(tmp_path), _txe(tmp_path), out)

    assert stats["ody_jsons"] == 3 and stats["filings"] == 1 and stats["meta"] is True
    assert (out / "case-summary.json").exists()
    assert (out / "filings" / "Petition.pdf").exists()
    assert (out / "meta.json").exists()
    manifest = json.loads((out / "combo-manifest.json").read_text())
    assert manifest["filings"] == 1 and manifest["meta"] is True
    # the staged folder is a valid provider intake the rest of the tools read
    case = main.Case.from_intake(out, case_dir=tmp_path / "x")
    assert case.case_number == "55-00-8"


def test_combine_without_txe_degrades_to_ody_only(tmp_path):
    out = tmp_path / "combo"
    stats = combine(_ody(tmp_path), None, out)
    assert stats["meta"] is False
    assert not (out / "meta.json").exists()
    assert (out / "filings" / "Petition.pdf").exists()


def test_combine_requires_ody_filings(tmp_path):
    bare = tmp_path / "ody"
    bare.mkdir()
    try:
        combine(bare, None, tmp_path / "combo")
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError as exc:
        assert "filings/" in str(exc)
