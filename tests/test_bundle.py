"""The capstone: `lawnlord bundle` wraps the complete case (standard metadata +
master PDF + per-page text + index) into one self-contained, cross-linked zip."""

import json
import zipfile

import fitz

import lawnlord as main


def _pdf(filings, name, pages):
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"{name} page {i + 1} summary judgment")
    doc.save(filings / name)
    doc.close()


def _combo_intake(tmp_path):
    """A real-PDF combo intake (ody JSONs + meta.json + valid filings)."""
    folder = tmp_path / "combo"
    filings = folder / "filings"
    filings.mkdir(parents=True)
    _pdf(filings, "Petition.pdf", 2)
    _pdf(filings, "Motion.pdf", 3)
    (folder / "case-summary.json").write_text(json.dumps({
        "caseNumber": "55-00-9", "caseTitle": "Acme v. Doe", "dateFiled": "01/02/2025",
    }))
    (folder / "case-history.json").write_text(json.dumps({
        "caseNumber": "55-00-9",
        "parties": [{"role": "Plaintiff", "name": "Acme"}],
        "timeline": [
            {"date": "2025-01-02", "phase": "Pleadings & Service",
             "event": "Original Petition", "files": ["filings/Petition.pdf"]},
            {"date": "2025-03-10", "phase": "Summary Judgment",
             "event": "Motion for Summary Judgment", "files": ["filings/Motion.pdf"]},
        ],
    }))
    (folder / "filings.json").write_text(json.dumps({
        "caseNumber": "55-00-9",
        "otherEventsOnThisCase": [
            {"date": "01/02/2025", "event": "Original Petition", "image": "Petition",
             "pageCount": 2, "file": "filings/Petition.pdf"},
            {"date": "03/10/2025", "event": "Motion for Summary Judgment",
             "image": "Motion", "pageCount": 3, "file": "filings/Motion.pdf"},
        ],
    }))
    (folder / "meta.json").write_text(json.dumps({
        "_meta": {"source": "re:SearchTX"},
        "caseInformation": {"caseNumber": "55-00-9", "caseCategory": "Civil - Other Civil"},
        "parties": {"rows": []},
        "hearings": {"rows": []},
        "events": {"rows": []},
    }))
    return folder


def _bundle(tmp_path):
    case = main.Case.from_intake(_combo_intake(tmp_path))
    out = tmp_path / "case.bundle.zip"
    stats = main.bundle_case(case, out)
    return out, stats


def test_bundle_is_self_contained_and_complete(tmp_path):
    out, stats = _bundle(tmp_path)
    assert stats["images"] == 2
    assert stats["pages"] == 5  # 2 + 3
    assert stats["master_pages"] == 5
    assert stats["text_lossless"] is True
    assert stats["missing"] == []
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
    # The required members are all present...
    assert {"case.json", "bundle-manifest.json", "case-master.pdf", "lawnlord.duckdb"} <= names
    assert "filings/Petition.pdf" in names and "filings/Motion.pdf" in names
    # ...and every entry is a relative path inside the bundle (no escapes).
    assert all(not n.startswith("/") and ".." not in n for n in names)


def test_reading_case_json_reaches_every_image(tmp_path):
    out, _ = _bundle(tmp_path)
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        case_json = json.loads(z.read("case.json"))
    # Each document's file path in case.json resolves to a real bundle entry.
    for doc in case_json["documents"]:
        assert doc["file"] in names


def test_bundle_manifest_cross_links_pages_and_master(tmp_path):
    out, _ = _bundle(tmp_path)
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        manifest = json.loads(z.read("bundle-manifest.json"))
        # The lossless proof rides inside the bundle.
        assert manifest["lossless"]["text"] is True
        for image in manifest["images"]:
            assert image["sha256"]  # hash-pinned
            assert image["file"] in names  # preserved original present
            # master-PDF page range is coherent
            assert image["masterPageStart"] <= image["masterPageEnd"]
            for page in image["pages"]:
                assert page["text"] in names  # per-page text present
                assert 1 <= page["masterPage"] <= 5


def test_bundle_cli_runs(tmp_path):
    from lawnlord import cli

    folder = _combo_intake(tmp_path)
    out = tmp_path / "out.bundle.zip"
    cli.main(["bundle", str(folder), "-o", str(out)])
    assert out.exists()
    with zipfile.ZipFile(out) as z:
        assert "case.json" in z.namelist()
