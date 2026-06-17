"""OCR hook: scanned (empty-text) pages get a tagged, recovered text layer."""

import argparse
import json

import fitz

import lawnlord as main
from lawnlord import cli


def _mixed_pdf_folder(tmp_path):
    """A folder with one PDF: page 1 has a text layer, page 2 is blank (a
    stand-in for a scanned page — get_text returns '')."""
    folder = tmp_path / "filings"
    folder.mkdir()
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "NATIVE TEXT PAGE")
    doc.new_page()  # blank: no text layer
    doc.save(folder / "doc.pdf")
    doc.close()
    return folder


def _fake_ocr(page):
    return ("OCR RECOVERED TEXT", 0.87)


def _analyses(corpus):
    return {
        p.name: json.loads(p.read_text())
        for p in corpus.glob("submissions/*/documents/*/sections/*/analysis/page-*.json")
    }


def test_ocr_fills_empty_pages_and_tags_provenance(tmp_path):
    folder = _mixed_pdf_folder(tmp_path)
    corpus = tmp_path / "corpus"
    main.write_corpus(folder, corpus, force=False, manual_boundaries={}, curation={},
                      ocr=_fake_ocr)
    texts = sorted(corpus.glob("submissions/*/documents/*/sections/*/text/page-*.txt"))
    bodies = [t.read_text() for t in texts]
    assert "NATIVE TEXT PAGE" in bodies[0]
    assert "OCR RECOVERED TEXT" in bodies[1]  # blank page recovered via OCR

    analyses = _analyses(corpus)
    p1 = analyses["page-001.json"]
    p2 = analyses["page-002.json"]
    assert p1["textSource"] == "native" and p1["ocrConfidence"] is None
    assert p2["textSource"] == "ocr" and p2["ocrConfidence"] == 0.87


def test_without_ocr_blank_pages_stay_empty(tmp_path):
    folder = _mixed_pdf_folder(tmp_path)
    corpus = tmp_path / "corpus"
    main.write_corpus(folder, corpus, force=False, manual_boundaries={}, curation={})
    analyses = _analyses(corpus)
    # No OCR: every page is native; the blank page's text file is empty.
    assert all(a["textSource"] == "native" for a in analyses.values())
    blank_text = next(
        corpus.glob("submissions/*/documents/*/sections/*/text/page-002.txt")
    ).read_text()
    assert blank_text.strip() == ""


def test_ocr_only_runs_on_empty_pages(tmp_path):
    folder = _mixed_pdf_folder(tmp_path)
    corpus = tmp_path / "corpus"
    calls = []

    def counting_ocr(page):
        calls.append(page.number)
        return ("X", 1.0)

    main.write_corpus(folder, corpus, force=False, manual_boundaries={}, curation={},
                      ocr=counting_ocr)
    # OCR invoked once — only for the blank page, not the native-text page.
    assert len(calls) == 1


def test_make_ocr_returns_callable():
    # The optional extra is installed in this dev env; make_ocr builds an engine.
    ocr = main.make_ocr()
    assert callable(ocr)


def test_make_ocr_gpu_path_is_safe():
    # use_gpu always returns a usable callable: CUDA when available, else a
    # warned CPU fallback (never raises just because there's no GPU).
    ocr = main.make_ocr(use_gpu=True)
    assert callable(ocr)


# --- F5a: OCR on by default, lazy, graceful ---------------------------------


def test_ocr_is_on_by_default_and_no_ocr_disables():
    # The build wires OCR ON by default (a lazy backend); --no-ocr opts out.
    on = cli._ocr_for(argparse.Namespace(no_ocr=False, gpu=False))
    off = cli._ocr_for(argparse.Namespace(no_ocr=True, gpu=False))
    assert callable(on)
    assert off is None


def test_lazy_ocr_degrades_when_extra_missing(monkeypatch):
    # If the engine can't be built (the 'ocr' extra is missing), the lazy
    # backend warns once and returns empty — it never raises into the build.
    def boom(*a, **k):
        raise RuntimeError("ocr extra missing")

    monkeypatch.setattr("lawnlord.ocr.make_ocr", boom)
    ocr = main.make_lazy_ocr()
    doc = fitz.open()
    doc.new_page()
    assert ocr(doc[0]) == ("", None)
    assert ocr(doc[0]) == ("", None)  # still safe after disabling
    doc.close()


def test_empty_ocr_result_leaves_page_native(tmp_path):
    # A degraded/empty OCR result must NOT mislabel the page as textSource=ocr;
    # it stays native + empty (and is flagged for review elsewhere).
    folder = _mixed_pdf_folder(tmp_path)
    corpus = tmp_path / "corpus"
    main.write_corpus(folder, corpus, force=False, manual_boundaries={}, curation={},
                      ocr=lambda page: ("", None))
    analyses = _analyses(corpus)
    assert analyses["page-002.json"]["textSource"] == "native"
    assert analyses["page-002.json"]["ocrConfidence"] is None
