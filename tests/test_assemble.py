"""The lossless explode <-> reassemble round-trip: reassembling the case's
images into one master PDF must lose no context — every page, in docket order,
under a Filing -> Image -> Document outline, with junk bookmarks excluded."""

import json

import fitz

import lawnlord as main


def _pdf(filings, name, pages, toc=None):
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"{name} page {i + 1}")
    if toc:
        doc.set_toc(toc)
    doc.save(filings / name)
    doc.close()


def _intake(tmp_path):
    """An intake whose 'Summary Judgment' filing bundles two images, one of
    which (MSJ.pdf) holds multiple documents-within plus junk bookmarks."""
    folder = tmp_path / "combo"
    filings = folder / "filings"
    filings.mkdir(parents=True)
    _pdf(filings, "Petition.pdf", 2)
    # MSJ bundles: MOTION (p1) + EXHIBIT A (p3); junk: an embedded-file-style
    # ".pdf" label (page -1) and a bare-numeric named destination.
    _pdf(filings, "MSJ.pdf", 4, toc=[
        [1, "MOTION", 1],
        [1, "EXHIBIT A", 3],
        [1, "acct-statement.pdf", -1],
        [1, "942358", 2],
    ])
    _pdf(filings, "Order.pdf", 1)
    (folder / "case-summary.json").write_text(json.dumps({"caseNumber": "55-00-1"}))
    (folder / "case-history.json").write_text(json.dumps({
        "caseNumber": "55-00-1",
        "parties": [{"role": "Plaintiff", "name": "Acme"}],
        "timeline": [
            {"date": "2025-01-01", "phase": "Pleadings & Service",
             "event": "Original Petition", "files": ["filings/Petition.pdf"]},
            {"date": "2025-03-01", "phase": "Summary Judgment", "event": "Summary Judgment",
             "files": ["filings/MSJ.pdf", "filings/Order.pdf"]},
        ],
    }))
    (folder / "filings.json").write_text(json.dumps({
        "caseNumber": "55-00-1",
        "otherEventsOnThisCase": [
            {"date": "01/01/2025", "event": "Original Petition", "image": "Petition",
             "pageCount": 2, "file": "filings/Petition.pdf"},
            {"date": "03/01/2025", "event": "Summary Judgment", "image": "MSJ",
             "pageCount": 4, "file": "filings/MSJ.pdf"},
            {"date": "03/01/2025", "event": "Summary Judgment", "image": "Order",
             "pageCount": 1, "file": "filings/Order.pdf"},
        ],
    }))
    return folder


def _assemble(tmp_path, name="case-master.pdf"):
    case = main.Case.from_intake(_intake(tmp_path))
    out = tmp_path / name
    stats = main.assemble_case(case, out)
    return case, out, stats


def test_roundtrip_is_text_lossless(tmp_path):
    _, _, stats = _assemble(tmp_path)
    assert stats["pages"] == 7  # 2 + 4 + 1, no page dropped or duplicated
    assert stats["images"] == 3
    assert stats["text_lossless"] is True
    assert stats["missing"] == []


def test_roundtrip_is_visually_lossless_and_accounts_extras(tmp_path):
    _, _, stats = _assemble(tmp_path)
    # Visual fidelity (numpy is available in the dev env): pages render the same.
    assert stats["visual_lossless"] is True
    assert stats["visual_worst_diff"] <= 2.0
    # Nothing silently lost: attachments carried and annotations preserved.
    assert stats["embedded_source"] == 0
    assert stats["embedded_attachments"] == stats["embedded_source"]
    assert stats["embedded_lossless"] is True
    assert stats["annotations_master"] == stats["annotations_source"]
    assert stats["annotations_lossless"] is True


def test_outline_is_filing_image_document(tmp_path):
    _, out, _ = _assemble(tmp_path)
    manifest = json.loads(out.with_suffix(".manifest.json").read_text())
    titles = [o["title"] for o in manifest["outline"]]
    # The hierarchy is present...
    assert "FILING: Original Petition (2025-01-01)" in titles
    assert "FILING: Summary Judgment (2025-03-01)" in titles
    assert "IMAGE: MSJ.pdf" in titles
    assert "DOC: MOTION" in titles and "DOC: EXHIBIT A" in titles
    # ...the multi-image filing gets ONE header, not one per image.
    assert titles.count("FILING: Summary Judgment (2025-03-01)") == 1
    # ...and junk bookmarks are NOT promoted to documents.
    assert not any("acct-statement.pdf" in t for t in titles)
    assert not any(t == "DOC: 942358" for t in titles)


def test_every_page_traces_to_a_source(tmp_path):
    _, out, stats = _assemble(tmp_path)
    manifest = json.loads(out.with_suffix(".manifest.json").read_text())
    prov = manifest["pageProvenance"]
    assert len(prov) == stats["pages"]
    # Each master page maps to a unique (image, source page).
    keys = {(p["image"], p["sourcePage"]) for p in prov}
    assert len(keys) == stats["pages"]
    # Docket order: the petition filing precedes the summary-judgment images.
    assert prov[0]["image"] == "Petition.pdf"
    assert prov[-1]["image"] == "Order.pdf"


def test_reassembly_is_deterministic(tmp_path):
    _, out_a, stats_a = _assemble(tmp_path, "a.pdf")
    # Re-run on the same intake (fresh Case) yields the same structure.
    case = main.Case.from_intake(tmp_path / "combo")
    out_b = tmp_path / "b.pdf"
    stats_b = main.assemble_case(case, out_b)
    assert (stats_a["pages"], stats_a["outline_entries"]) == (stats_b["pages"], stats_b["outline_entries"])
    man_a = json.loads(out_a.with_suffix(".manifest.json").read_text())["outline"]
    man_b = json.loads(out_b.with_suffix(".manifest.json").read_text())["outline"]
    assert man_a == man_b


def test_missing_image_is_reported_not_fatal(tmp_path):
    folder = _intake(tmp_path)
    (folder / "filings" / "Order.pdf").unlink()  # referenced by a filing, now gone
    case = main.Case.from_intake(folder)
    stats = main.assemble_case(case, tmp_path / "m.pdf")
    assert "filings/Order.pdf" in stats["missing"]
    assert stats["pages"] == 6  # the surviving images still reassemble
    assert stats["text_lossless"] is True
