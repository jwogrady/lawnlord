"""Golden / characterization test for the whole detection pipeline against the
real source packet.

This is the single most important freeze before refactoring: it runs the same
read-only inspection the `--dry-run` does and pins the documented build
baseline (20 PDFs / 251 pages / 46 sections, all confidence 1.00). If the
canonical zip is absent, the test skips rather than fails, so the suite still
runs without the corpus.

Source of the expected numbers: CLAUDE.md "Counts" + the `--dry-run` summary.
"""

import pytest

import lawnlord as main

# Documented build baseline (manual boundaries applied).
EXPECTED_TOTAL_ENTRIES = 21
EXPECTED_PDF_COUNT = 20
EXPECTED_TOTAL_PAGES = 251
EXPECTED_TOTAL_SECTIONS = 46


@pytest.fixture(scope="module")
def baseline_report():
    if not main.DEFAULT_ZIP_CANDIDATES[0].exists():
        pytest.skip(f"canonical packet not present: {main.DEFAULT_ZIP_CANDIDATES[0]}")
    zip_path = main.resolve_zip_path(None)
    manual = main.load_manual_boundaries()
    return main.inspect_archive(zip_path, manual)


def test_archive_entry_counts(baseline_report):
    report = baseline_report
    assert report["totalEntries"] == EXPECTED_TOTAL_ENTRIES
    assert len(report["pdfEntries"]) == EXPECTED_PDF_COUNT
    assert report["nestedZips"] == []
    assert report["suspiciousEntries"] == []


def test_all_pdfs_readable(baseline_report):
    for entry in baseline_report["pdfEntries"]:
        assert entry.error == "", f"{entry.filename}: {entry.error}"
        assert entry.page_count is not None


def test_total_page_count(baseline_report):
    total = sum(e.page_count for e in baseline_report["pdfEntries"])
    assert total == EXPECTED_TOTAL_PAGES


def test_total_section_count(baseline_report):
    total = sum(len(e.sections) for e in baseline_report["pdfEntries"])
    assert total == EXPECTED_TOTAL_SECTIONS


def test_every_document_is_fully_covered(baseline_report):
    # Chain-of-custody invariant: sections cover 1..N with no gaps/overlaps.
    for entry in baseline_report["pdfEntries"]:
        assert main.covers_exactly(entry.sections, entry.page_count), entry.filename


def test_baseline_all_confidence_one(baseline_report):
    # The manual-boundary baseline is entirely confidence 1.00, so nothing is
    # flagged for human review.
    for entry in baseline_report["pdfEntries"]:
        for section in entry.sections:
            assert section.confidence == main.CONFIDENCE_MANUAL, entry.filename
            assert section.detection_tier == main.TIER_MANUAL


def test_baseline_nothing_needs_review(baseline_report):
    for entry in baseline_report["pdfEntries"]:
        for i, section in enumerate(entry.sections):
            summary = main.section_summary(section, i, entry.sha256 or "0" * 16)
            assert summary["needsHumanReview"] is False
