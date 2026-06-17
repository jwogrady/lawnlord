"""Folder source: explode a directory of loose PDFs (not a ZIP)."""

import fitz

import lawnlord as main


def _pdf_bytes(pages: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_folder(tmp_path, files: dict[str, list[str]]):
    folder = tmp_path / "filings"
    folder.mkdir()
    for name, pages in files.items():
        (folder / name).write_bytes(_pdf_bytes(pages))
    return folder


def test_inspect_folder_reads_loose_pdfs(tmp_path):
    folder = _make_folder(
        tmp_path,
        {"b.pdf": ["MOTION", "body"], "a.pdf": ["FINAL JUDGMENT"]},
    )
    report = main.inspect_folder(folder)
    # Sorted, so deterministic order regardless of filesystem.
    assert [e.filename for e in report["pdfEntries"]] == ["a.pdf", "b.pdf"]
    assert report["totalEntries"] == 2
    assert all(e.source_path for e in report["pdfEntries"])  # on-disk path set
    assert sum(e.page_count for e in report["pdfEntries"]) == 3


def test_uppercase_pdf_extension_is_included(tmp_path):
    # A portal-supplied ".PDF" must not be silently dropped (ZIP mode matches
    # case-insensitively; folder mode must too).
    folder = tmp_path / "filings"
    folder.mkdir()
    (folder / "UPPER.PDF").write_bytes(_pdf_bytes(["X"]))
    report = main.inspect_folder(folder)
    assert [e.filename for e in report["pdfEntries"]] == ["UPPER.PDF"]


def test_inspect_source_dispatches_dir_vs_zip(tmp_path):
    folder = _make_folder(tmp_path, {"a.pdf": ["X"]})
    # Directory -> folder mode.
    assert main.inspect_source(folder)["zipPath"] == folder
    assert len(main.inspect_source(folder)["pdfEntries"]) == 1


def test_folder_archive_id_is_deterministic(tmp_path):
    folder = _make_folder(tmp_path, {"a.pdf": ["X"], "b.pdf": ["Y"]})
    assert main.inspect_folder(folder)["zipSha256"] == main.inspect_folder(folder)["zipSha256"]


def test_build_corpus_from_folder(tmp_path):
    folder = _make_folder(
        tmp_path,
        {
            "doc-one.pdf": ["MOTION FOR NEW TRIAL", "body", "EXHIBIT A"],
            "doc-two.pdf": ["FINAL SUMMARY JUDGMENT"],
        },
    )
    corpus = tmp_path / "corpus"
    manifest = main.write_corpus(
        folder, corpus, force=False, manual_boundaries={}, curation={}
    )
    subs = manifest["submissions"]
    assert sum(s["documentCount"] for s in subs) == 2
    assert sum(s["pageCount"] for s in subs) == 4
    assert manifest["archive"]["pdfCount"] == 2
    # source.pdf was written for each document (bytes read from disk, not a zip).
    written = sorted(corpus.glob("submissions/*/documents/*/source.pdf"))
    assert len(written) == 2
    # Full per-document page coverage preserved in folder mode.
    for entry in main.inspect_folder(folder)["pdfEntries"]:
        assert main.covers_exactly(entry.sections, entry.page_count)


def test_changed_source_under_same_name_is_reextracted(tmp_path):
    # A re-run reuses an existing submission only when the source bytes match.
    # If the source under the same name changes, the stale extraction must be
    # rebuilt — otherwise its pages won't line up with the rebuilt index/master.
    folder = _make_folder(tmp_path, {"doc-one.pdf": ["ORIGINAL"]})
    corpus = tmp_path / "corpus"
    m1 = main.write_corpus(folder, corpus, force=False, manual_boundaries={}, curation={})
    id1 = m1["submissions"][0]["submissionId"]

    # Same filename (same slug), different content + page count.
    (folder / "doc-one.pdf").write_bytes(_pdf_bytes(["REPLACED", "page two"]))
    m2 = main.write_corpus(folder, corpus, force=False, manual_boundaries={}, curation={})
    assert m2["submissions"][0]["submissionId"] != id1  # content-keyed id changed
    assert m2["submissions"][0]["pageCount"] == 2  # reflects the new 2-page source

    # An unchanged re-run keeps the same id (genuine reuse, the fast path).
    m3 = main.write_corpus(folder, corpus, force=False, manual_boundaries={}, curation={})
    assert m3["submissions"][0]["submissionId"] == m2["submissions"][0]["submissionId"]
