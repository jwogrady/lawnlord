"""The `section == document` decision (issue #34).

The exploder detects one boundary level — the documents *within* an image (a
Motion, Exhibit A, an Affidavit) — and the index stores them as `documents`.
There is no separate first-class `section` level: the on-disk "section"
vocabulary maps to a `documents` row at the index boundary, and junk bookmarks
are excluded from the document set.
"""

import fitz

import lawnlord as main
from lawnlord.assemble import _is_junk_bookmark
from lawnlord.db import apply_schema, open_case_db


def _pdf_with_toc(path, page_count, toc):
    doc = fitz.open()
    for _ in range(page_count):
        doc.new_page()
    doc.set_toc(toc)
    doc.save(path)
    doc.close()


def test_index_models_documents_not_sections(tmp_path):
    # section == document: documents-within-an-image are stored in `documents`;
    # there is no separate `sections` table.
    con = open_case_db(tmp_path / "c.duckdb")
    apply_schema(con)
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    con.close()
    assert "documents" in tables
    assert "sections" not in tables


def test_bookmarks_yield_one_document_per_real_bookmark(tmp_path):
    # The MSJ shape: an image whose nine top-level bookmarks (Motion + Exhibits
    # A-D + Affidavit + ...) explode into nine documents, each a contiguous page
    # range with full 1..N coverage. A sub-level (level 2) entry is not a
    # document boundary and is excluded.
    pdf = tmp_path / "msj.pdf"
    titles = [
        "Motion for Summary Judgment",
        "Exhibit A",
        "Exhibit B",
        "Exhibit C",
        "Exhibit D",
        "Affidavit",
        "Proposed Order",
        "Certificate of Service",
        "Appendix",
    ]
    toc = [[1, title, i + 1] for i, title in enumerate(titles)]
    toc.insert(2, [2, "A subheading inside Exhibit A", 2])  # level 2 -> not a boundary
    _pdf_with_toc(pdf, len(titles), toc)

    doc = fitz.open(pdf)
    sections = main.detect_sections_in_doc(doc, "msj.pdf", "msj")
    doc.close()

    assert len(sections) == len(titles)  # nine documents; the sub-level is excluded
    assert [s.title for s in sections] == titles
    assert main.covers_exactly(sections, len(titles)) is True


def test_is_junk_bookmark_excludes_noise_keeps_real_titles():
    # Junk excluded from the document set: embedded-file/remote targets
    # (page < 1), empty titles, filename-like titles, and bare numeric ids.
    assert _is_junk_bookmark("ExhibitA.pdf", 3) is True
    assert _is_junk_bookmark("12345", 3) is True
    assert _is_junk_bookmark("", 3) is True
    assert _is_junk_bookmark("Motion", -1) is True  # embedded / remote target
    assert _is_junk_bookmark("Motion for Summary Judgment", 1) is False
    assert _is_junk_bookmark("Exhibit A", 2) is False


# ---------------------------------------------------------------------------
# Additive-only invariant (issue #37): no overlay/proposal/verdict can mutate
# the mirrored record or its generated provenance.
# ---------------------------------------------------------------------------


def test_overlay_never_mutates_generated_provenance():
    provenance = {
        "sha256": "abc123",
        "sourcePageStart": 1,
        "sourcePageEnd": 3,
        "sectionSlug": "motion",
        "detectionTier": "bookmarks",
        "boundaryConfidence": 0.95,
        "pdfPath": "sections/001-motion/pages/page-001.pdf",
        "citation": {"lowLevel": "motion p.1"},
    }
    base = {**provenance, "status": "", "tags": []}
    before = {k: base[k] for k in provenance}

    hostile = {
        # legitimate curated edits (whitelisted)
        "status": "reviewed",
        "tags": ["msj"],
        # attempts to overwrite generated provenance — must be ignored
        "sha256": "TAMPERED",
        "sourcePageStart": 999,
        "sectionSlug": "hacked",
        "detectionTier": "manual",
        "boundaryConfidence": 1.0,
        "pdfPath": "/etc/passwd",
        "citation": {"lowLevel": "fake"},
        # injected analysis / verdict fields — not whitelisted
        "legalSummary": "a conclusion",
        "verdict": "accepted",
    }
    main.apply_metadata_overlay(base, hostile, main.ALLOWED_CURATED_FIELDS)

    assert {k: base[k] for k in provenance} == before  # provenance byte-identical
    assert base["status"] == "reviewed" and base["tags"] == ["msj"]  # allowed applied
    assert "legalSummary" not in base and "verdict" not in base  # injections rejected


def test_whitelist_is_the_single_chokepoint_excludes_provenance():
    # The whitelist must never include a generated/provenance field, or an
    # overlay could overwrite the mirrored record. This fails if one creeps in.
    protected = {
        "sha256", "sourcePageStart", "sourcePageEnd", "sectionId", "sectionSlug",
        "documentSlug", "detectionTier", "boundaryConfidence", "sourcePdf",
        "sourceText", "pdfPath", "textPath", "citation", "pageImagePath",
        "pageImageSha256",
    }
    assert main.ALLOWED_CURATED_FIELDS.isdisjoint(protected)
