"""Corpus index: explode + ingest + index sections/chunks into DuckDB."""

import json

import fitz
import pytest

import lawnlord as main
from lawnlord import cli

GEN = "2026-06-16T00:00:00Z"


def _pdf(filings, name, pages):
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"{name} page {i + 1}")
    doc.save(filings / name)
    doc.close()


def _intake(tmp_path):
    """A provider intake folder with two real PDFs and matching metadata.
    Motion.pdf is declared at 99 pages but is really 1 — a deliberate
    declared-vs-actual mismatch for the cross-check."""
    folder = tmp_path / "ody"
    filings = folder / "filings"
    filings.mkdir(parents=True)
    _pdf(filings, "Petition.pdf", 2)
    _pdf(filings, "Motion.pdf", 1)
    (folder / "case-summary.json").write_text(json.dumps({"caseNumber": "55-00-1"}))
    (folder / "case-history.json").write_text(json.dumps({
        "caseNumber": "55-00-1",
        "parties": [{"role": "Plaintiff", "name": "Acme"}],
        "timeline": [
            {"date": "2025-01-01", "phase": "Pleadings & Service",
             "event": "Original Petition", "files": ["filings/Petition.pdf"]},
            {"date": "2025-03-01", "phase": "Summary Judgment",
             "event": "Motion for Summary Judgment", "files": ["filings/Motion.pdf"]},
        ],
    }))
    (folder / "filings.json").write_text(json.dumps({
        "caseNumber": "55-00-1",
        "otherEventsOnThisCase": [
            {"date": "01/01/2025", "event": "Original Petition",
             "image": "Petition", "pageCount": 2, "file": "filings/Petition.pdf"},
            {"date": "03/01/2025", "event": "Motion for Summary Judgment",
             "image": "Motion", "pageCount": 99, "file": "filings/Motion.pdf"},
        ],
    }))
    return folder


def _index(tmp_path):
    folder = _intake(tmp_path)
    case = main.Case.from_intake(folder, case_dir=tmp_path / "out")
    manifest = main.write_corpus(
        case.filings_dir, case.corpus_dir, force=False, manual_boundaries={}, curation={}
    )
    con = main.open_case_db(case.duckdb_path)
    main.apply_schema(con)
    main.ingest_case(con, case, manifest["generatedAt"])
    stats = main.index_corpus(con, case, case.corpus_dir, manifest["generatedAt"])
    return case, con, stats


def test_index_counts(tmp_path):
    case, con, stats = _index(tmp_path)
    assert stats["chunks"] == 3  # 2 + 1 pages
    assert stats["documents"] >= 2
    assert con.execute("SELECT count(*) FROM chunks").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM documents").fetchone()[0] == stats["documents"]


def test_chunks_have_provenance(tmp_path):
    case, con, stats = _index(tmp_path)
    bad = con.execute(
        "SELECT count(*) FROM chunks WHERE document_id IS NULL "
        "OR source_page_number IS NULL OR citation_display = ''"
    ).fetchone()[0]
    assert bad == 0


def test_declared_vs_actual_cross_check(tmp_path):
    case, con, stats = _index(tmp_path)
    # Motion declared 99 but is 1 page -> flagged; Petition (2==2) -> not.
    assert any(m["actual"] == 1 and m["declared"] == 99 for m in stats["mismatches"])
    motion = con.execute(
        "SELECT actual_page_count, page_count_mismatch FROM images "
        "WHERE filename = 'Motion.pdf'"
    ).fetchone()
    assert motion == (1, True)
    petition = con.execute(
        "SELECT actual_page_count, page_count_mismatch FROM images "
        "WHERE filename = 'Petition.pdf'"
    ).fetchone()
    assert petition == (2, False)


def test_reindex_is_deterministic(tmp_path):
    case, con, stats = _index(tmp_path)

    def dump():
        return {
            t: con.execute(f"SELECT * FROM {t} ORDER BY ALL").fetchall()
            for t in ("documents", "chunks")
        }

    first = dump()
    main.index_corpus(con, case, case.corpus_dir, GEN)  # re-index same corpus
    # created_at differs only if generated_at differs; re-run with the corpus's
    # own generatedAt to confirm byte-identical.
    manifest_gen = json.loads((case.corpus_dir / "manifest.json").read_text())["generatedAt"]
    main.index_corpus(con, case, case.corpus_dir, manifest_gen)
    assert dump() == first


def test_integrity_guard_raises_on_dropped_page(tmp_path):
    case, con, stats = _index(tmp_path)
    # Corrupt a toc: drop a page from the 2-page Petition document.
    toc_path = next(case.corpus_dir.glob("submissions/*petition*/documents/*/toc.json"))
    toc = json.loads(toc_path.read_text())
    toc["sections"][0]["pages"] = toc["sections"][0]["pages"][:-1]
    toc_path.write_text(json.dumps(toc))
    with pytest.raises(ValueError, match="page coverage broken"):
        main.index_corpus(con, case, case.corpus_dir, GEN)


def test_duplicate_page_caught_before_insert(tmp_path):
    # A duplicate sourcePageNumber that still sums to actual must be caught by
    # the coverage guard (before any insert) — not slip through to a PK error.
    case, con, stats = _index(tmp_path)
    toc_path = next(case.corpus_dir.glob("submissions/*petition*/documents/*/toc.json"))
    toc = json.loads(toc_path.read_text())
    toc["sections"][0]["pages"][1]["sourcePageNumber"] = 1  # [1,1], sums to 2
    toc_path.write_text(json.dumps(toc))
    assert con.execute("SELECT count(*) FROM chunks").fetchone()[0] == 3
    with pytest.raises(ValueError, match="page coverage broken"):
        main.index_corpus(con, case, case.corpus_dir, GEN)
    # Atomic: the failed re-index rolled back, so the prior good index survives
    # intact rather than being left half-written.
    assert con.execute("SELECT count(*) FROM chunks").fetchone()[0] == 3


def test_undocketed_document_is_counted_not_hidden(tmp_path):
    # A corpus PDF absent from filings.json is indexed but surfaced as orphan.
    folder = _intake(tmp_path)
    (folder / "filings.json").write_text(json.dumps({"caseNumber": "55-00-1"}))
    case = main.Case.from_intake(folder, case_dir=tmp_path / "out")
    manifest = main.write_corpus(
        case.filings_dir, case.corpus_dir, force=False, manual_boundaries={}, curation={}
    )
    con = main.open_case_db(case.duckdb_path)
    main.apply_schema(con)
    main.ingest_case(con, case, manifest["generatedAt"])
    stats = main.index_corpus(con, case, case.corpus_dir, manifest["generatedAt"])
    assert stats["orphan_images"] == 2  # both PDFs undocketed
    assert stats["chunks"] == 3  # still indexed


def test_missing_manifest_raises(tmp_path):
    case = main.Case.from_intake(_intake(tmp_path), case_dir=tmp_path / "out")
    con = main.open_case_db(case.duckdb_path)
    main.apply_schema(con)
    with pytest.raises(FileNotFoundError):
        main.index_corpus(con, case, tmp_path / "no-corpus", GEN)


def test_index_cli_end_to_end(tmp_path):
    folder = _intake(tmp_path)
    out = tmp_path / "out"
    cli.main(["index", str(folder), "--case-dir", str(out)])
    con = main.open_case_db(out / "lawnlord.duckdb")
    assert con.execute("SELECT count(*) FROM chunks").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM images").fetchone()[0] == 2


def test_content_schema_page_pointer(tmp_path):
    # Every page chunk carries its text provenance and a pointer to its
    # preserved page image: a corpus-relative path that resolves, and a sha256
    # that matches the bytes on disk (#31).
    from lawnlord.hashing import sha256_file

    case, con, stats = _index(tmp_path)
    rows = con.execute(
        "SELECT page_image_path, page_image_sha256, text_source FROM chunks"
    ).fetchall()
    assert rows and len(rows) == stats["chunks"]
    for path, sha, source in rows:
        assert path and sha  # no nulls — a page is reconstructable from the data
        resolved = case.corpus_dir / path
        assert resolved.exists()  # the pointer resolves to a preserved page image
        assert sha256_file(resolved) == sha  # and the sha256 pins those bytes
        assert source == "native"  # synthetic PDFs carry a real text layer
