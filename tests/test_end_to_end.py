"""End-to-end freeze of the build pipeline against synthetic PDFs.

Replaces the old case-specific baseline (which froze one real packet's
20/251/46 counts). A generic tool can't depend on a particular packet, so this
generates a tiny ZIP of PDFs in tmp_path and pins the structural invariants
that must hold for ANY input: full per-document page coverage, the page totals,
the citation model, and the never-pre-filled page-analysis stub.
"""

import json
import zipfile

import fitz

import lawnlord as main


def _pdf_bytes(pages: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_packet(tmp_path, files: dict[str, list[str]]):
    packet = tmp_path / "packet.zip"
    with zipfile.ZipFile(packet, "w") as z:
        for name, pages in files.items():
            z.writestr(name, _pdf_bytes(pages))
    return packet


def test_build_explodes_with_full_coverage_and_provenance(tmp_path):
    packet = _make_packet(
        tmp_path,
        {
            "doc-one.pdf": ["MOTION FOR NEW TRIAL", "ordinary body text", "EXHIBIT A"],
            "doc-two.pdf": ["FINAL SUMMARY JUDGMENT"],
        },
    )
    corpus = tmp_path / "corpus"

    manifest = main.write_corpus(
        packet, corpus, force=False, manual_boundaries={}, curation={}
    )

    # One submission per source PDF; page totals add up.
    subs = manifest["submissions"]
    assert len(subs) == 2
    assert sum(s["documentCount"] for s in subs) == 2
    assert sum(s["pageCount"] for s in subs) == 4
    assert manifest["archive"]["pdfCount"] == 2
    assert manifest["archive"]["totalPageCount"] == 4

    # Chain-of-custody: every document's sections cover 1..N exactly.
    report = main.inspect_archive(packet, {})
    for entry in report["pdfEntries"]:
        assert main.covers_exactly(entry.sections, entry.page_count), entry.filename

    # The on-disk corpus exists with the expected shape.
    assert (corpus / "manifest.json").exists()
    assert (corpus / "archive.json").exists()


def test_page_analysis_stub_is_unfilled_and_carries_citation(tmp_path):
    packet = _make_packet(tmp_path, {"only.pdf": ["FINAL SUMMARY JUDGMENT", "page two"]})
    corpus = tmp_path / "corpus"
    main.write_corpus(packet, corpus, force=False, manual_boundaries={}, curation={})

    analyses = sorted(corpus.glob("submissions/*/documents/*/sections/*/analysis/page-*.json"))
    assert analyses, "expected page-analysis stubs"
    data = json.loads(analyses[0].read_text(encoding="utf-8"))

    # Provenance + citation model.
    assert data["sourcePageNumber"] >= 1
    assert data["citation"]["lowLevel"] == f"{data['documentSlug']} p.{data['sourcePageNumber']}"
    assert data["citation"]["display"].endswith(f"p.{data['sourcePageNumber']}")

    # Never pre-filled: empty legal placeholders + flagged for review.
    assert data["needsReview"] is True
    assert data["legalSummary"] == ""
    assert data["keyFacts"] == []
