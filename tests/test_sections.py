"""Characterization tests for section assembly, coverage validation, manual
boundary parsing, summary shape, and review-preservation keys.

These exercise the section-building logic without needing a real PDF, by
feeding synthetic boundary inputs. The end-to-end detection against the real
packet is frozen separately in test_baseline.py.
"""

import lawnlord as main
from lawnlord import SectionBoundary


def _sb(start, end, title="Sec", confidence=1.0, tier=main.TIER_MANUAL):
    return SectionBoundary(
        title=title,
        slug="",
        start_page=start,
        end_page=end,
        confidence=confidence,
        reason="r",
        detection_tier=tier,
    )


# ---------------------------------------------------------------------------
# covers_exactly
# ---------------------------------------------------------------------------


def test_covers_exactly_contiguous_is_true():
    assert main.covers_exactly([_sb(1, 2), _sb(3, 5)], 5) is True
    assert main.covers_exactly([_sb(1, 5)], 5) is True


def test_covers_exactly_detects_gap():
    assert main.covers_exactly([_sb(1, 2), _sb(4, 5)], 5) is False


def test_covers_exactly_detects_overlap():
    assert main.covers_exactly([_sb(1, 3), _sb(3, 5)], 5) is False


def test_covers_exactly_detects_short_coverage():
    assert main.covers_exactly([_sb(1, 4)], 5) is False


# ---------------------------------------------------------------------------
# build_sections
# ---------------------------------------------------------------------------


def test_build_sections_makes_contiguous_full_coverage():
    starts = [
        (1, "First Motion", 0.65, "r", main.TIER_HEADING_SCAN),
        (3, "EXHIBIT A", 0.65, "r", main.TIER_HEADING_SCAN),
    ]
    sections = main.build_sections(starts, 5)
    assert [(s.start_page, s.end_page) for s in sections] == [(1, 2), (3, 5)]
    assert main.covers_exactly(sections, 5) is True
    # documentFamily is inferred from the title.
    assert sections[0].document_family == "motion"
    assert sections[1].document_family == "exhibit"


def test_build_sections_assigns_unique_slugs():
    starts = [
        (1, "Same", 0.65, "r", main.TIER_HEADING_SCAN),
        (2, "Same", 0.65, "r", main.TIER_HEADING_SCAN),
    ]
    sections = main.build_sections(starts, 3)
    slugs = [s.slug for s in sections]
    assert len(set(slugs)) == len(slugs)
    assert slugs[0] == "same"
    assert slugs[1] == "same-p2"


# ---------------------------------------------------------------------------
# finalize_slugs
# ---------------------------------------------------------------------------


def test_finalize_slugs_dedupes_within_document():
    sections = [_sb(1, 1, title="Order"), _sb(2, 2, title="Order")]
    main.finalize_slugs(sections)
    assert sections[0].slug == "order"
    assert sections[1].slug == "order-p2"


# ---------------------------------------------------------------------------
# sections_from_manual
# ---------------------------------------------------------------------------


def test_sections_from_manual_parses_valid_entries():
    entries = [
        {"startPage": 1, "endPage": 2, "title": "Motion", "documentFamily": "motion"},
        {"startPage": 3, "endPage": 5, "title": "Exhibit A"},
    ]
    sections = main.sections_from_manual(entries, 5, "doc.pdf")
    assert len(sections) == 2
    assert sections[0].confidence == main.CONFIDENCE_MANUAL
    assert sections[0].detection_tier == main.TIER_MANUAL
    assert sections[0].document_family == "motion"
    assert sections[1].title == "Exhibit A"


def test_sections_from_manual_skips_out_of_range_and_malformed():
    entries = [
        {"startPage": 1, "endPage": 2},  # valid
        {"startPage": 4, "endPage": 99},  # end out of range -> skipped
        {"startPage": "x", "endPage": 3},  # non-int -> skipped
        ["not", "a", "dict"],  # wrong type -> skipped
        {"endPage": 3},  # missing startPage -> skipped
    ]
    sections = main.sections_from_manual(entries, 5, "doc.pdf")
    assert len(sections) == 1
    assert (sections[0].start_page, sections[0].end_page) == (1, 2)


# ---------------------------------------------------------------------------
# manual_entries_for (key resolution shapes)
# ---------------------------------------------------------------------------


def test_manual_entries_for_top_level_by_filename():
    manual = {"doc.pdf": [{"startPage": 1, "endPage": 1}]}
    assert main.manual_entries_for(manual, "folder/doc.pdf", "doc.pdf") == [
        {"startPage": 1, "endPage": 1}
    ]


def test_manual_entries_for_documents_wrapper_with_sections_key():
    manual = {"documents": {"doc.pdf": {"sections": [{"startPage": 1, "endPage": 1}]}}}
    assert main.manual_entries_for(manual, "folder/doc.pdf", "doc.pdf") == [
        {"startPage": 1, "endPage": 1}
    ]


def test_manual_entries_for_prefers_zip_path_key():
    manual = {
        "folder/doc.pdf": [{"startPage": 1, "endPage": 2}],
        "doc.pdf": [{"startPage": 1, "endPage": 1}],
    }
    assert main.manual_entries_for(manual, "folder/doc.pdf", "doc.pdf") == [
        {"startPage": 1, "endPage": 2}
    ]


def test_manual_entries_for_missing_returns_none():
    assert main.manual_entries_for({}, "folder/doc.pdf", "doc.pdf") is None


# ---------------------------------------------------------------------------
# section_summary (the data contract)
# ---------------------------------------------------------------------------


def test_section_summary_field_names_and_id_format():
    section = SectionBoundary(
        title="Final Summary Judgment",
        slug="final-summary-judgment",
        start_page=1,
        end_page=3,
        confidence=1.0,
        reason="Manual boundary",
        detection_tier=main.TIER_MANUAL,
        document_family="judgment",
    )
    summary = main.section_summary(section, 0, "abcdef0123456789")
    assert summary == {
        "sectionIndex": 0,
        "sectionId": "sec_abcdef012345_p001-p003",
        "title": "Final Summary Judgment",
        "sectionSlug": "final-summary-judgment",
        "sourcePageStart": 1,
        "sourcePageEnd": 3,
        "pageCount": 3,
        "boundaryConfidence": 1.0,
        "reason": "Manual boundary",
        "detectionTier": "manual",
        "documentFamily": "judgment",
        "needsHumanReview": False,
    }


def test_section_summary_flags_low_confidence_for_review():
    section = _sb(1, 1, confidence=main.CONFIDENCE_HEADING, tier=main.TIER_HEADING_SCAN)
    summary = main.section_summary(section, 0, "0" * 16)
    assert summary["needsHumanReview"] is True


def test_section_summary_uses_no_legacy_field_names():
    section = _sb(1, 1)
    summary = main.section_summary(section, 0, "0" * 16)
    for legacy in ("startPage", "endPage", "confidence"):
        assert legacy not in summary


# ---------------------------------------------------------------------------
# confidence_distribution
# ---------------------------------------------------------------------------


def test_confidence_distribution_counts_and_sorts_descending():
    sections = [_sb(1, 1, confidence=1.0), _sb(2, 2, confidence=1.0), _sb(3, 3, confidence=0.65)]
    dist = main.confidence_distribution(sections)
    assert dist == {"1.00": 2, "0.65": 1}
    assert list(dist.keys()) == ["1.00", "0.65"]


# ---------------------------------------------------------------------------
# Review-preservation predicates and keys
# ---------------------------------------------------------------------------


def test_is_reviewed_analysis_only_when_needs_review_is_false():
    assert main.is_reviewed_analysis({"needsReview": False}) is True
    assert main.is_reviewed_analysis({"needsReview": True}) is False
    assert main.is_reviewed_analysis({}) is False
    # Truthy/falsey lookalikes are not the literal False.
    assert main.is_reviewed_analysis({"needsReview": 0}) is False


def test_preservation_exact_key_full_and_missing():
    data = {
        "archiveId": "arc",
        "submissionSlug": "sub",
        "documentSlug": "doc",
        "sectionSlug": "sec",
        "sourcePageNumber": 4,
    }
    assert main.preservation_exact_key(data) == ("arc", "sub", "doc", "sec", 4)
    del data["sectionSlug"]
    assert main.preservation_exact_key(data) is None


def test_preservation_fallback_key_full_and_missing():
    data = {"submissionSlug": "sub", "documentSlug": "doc", "sourcePageNumber": 4}
    assert main.preservation_fallback_key(data) == ("sub", "doc", 4)
    del data["sourcePageNumber"]
    assert main.preservation_fallback_key(data) is None
