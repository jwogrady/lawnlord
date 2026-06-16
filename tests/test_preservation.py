"""Characterization tests for the --force review-preservation pair:
collect_reviewed_analysis() and apply_preserved_analysis().

These build a synthetic corpus tree in tmp_path (the same
submissions/*/documents/*/sections/*/analysis/page-*.json layout a real build
writes) and pin the indexing stats and the exact field-copy behavior, so a
refactor of the preservation path can't silently drop reviewed legal work.
"""

import json

import lawnlord as main


def _write_page(corpus, sub, doc, sec, filename, data):
    analysis_dir = (
        corpus / "submissions" / sub / "documents" / doc / "sections" / sec / "analysis"
    )
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / filename).write_text(json.dumps(data), encoding="utf-8")


def _page(**overrides):
    base = {
        "archiveId": "arc",
        "submissionSlug": "sub-a",
        "documentSlug": "doc-a",
        "sectionSlug": "sec-a",
        "sourcePageNumber": 1,
        "needsReview": False,
        "legalSummary": "reviewed summary",
        "keyFacts": ["fact one"],
        "reviewedBy": "jwogrady",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# collect_reviewed_analysis
# ---------------------------------------------------------------------------


def test_collect_indexes_a_reviewed_page(tmp_path):
    _write_page(tmp_path, "sub-a", "doc-a", "sec-a", "page-001.json", _page())
    index, stats = main.collect_reviewed_analysis(tmp_path)

    assert stats == {"discovered": 1, "indexed": 1, "invalid": 0, "duplicates": 0, "unmatched": 0}
    assert index["exact"][("arc", "sub-a", "doc-a", "sec-a", 1)]["data"]["legalSummary"] == (
        "reviewed summary"
    )
    assert ("sub-a", "doc-a", 1) in index["fallback"]


def test_collect_skips_unreviewed_pages(tmp_path):
    _write_page(tmp_path, "sub-a", "doc-a", "sec-a", "page-001.json", _page(needsReview=True))
    index, stats = main.collect_reviewed_analysis(tmp_path)

    assert stats["discovered"] == 1
    assert stats["indexed"] == 0
    assert index["exact"] == {}
    assert index["fallback"] == {}


def test_collect_counts_invalid_json(tmp_path):
    analysis_dir = (
        tmp_path / "submissions" / "sub-a" / "documents" / "doc-a" / "sections" / "sec-a" / "analysis"
    )
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "page-001.json").write_text("{not valid json", encoding="utf-8")

    _, stats = main.collect_reviewed_analysis(tmp_path)
    assert stats["discovered"] == 1
    assert stats["invalid"] == 1
    assert stats["indexed"] == 0


def test_collect_counts_reviewed_but_unidentifiable_as_unmatched(tmp_path):
    # Reviewed, but missing submissionSlug -> both exact and fallback keys are
    # None, so it can never be matched and is counted as unmatched, not indexed.
    page = _page()
    del page["submissionSlug"]
    _write_page(tmp_path, "sub-a", "doc-a", "sec-a", "page-001.json", page)

    index, stats = main.collect_reviewed_analysis(tmp_path)
    assert stats["unmatched"] == 1
    assert stats["indexed"] == 0
    assert index["exact"] == {}


def test_collect_dedupes_keeping_first_in_sorted_path_order(tmp_path):
    # Two reviewed pages with identical identity fields in different section
    # dirs. Sorted path order keeps sec-a; sec-b is a duplicate.
    _write_page(tmp_path, "sub-a", "doc-a", "sec-a", "page-001.json", _page(legalSummary="first"))
    _write_page(tmp_path, "sub-a", "doc-a", "sec-b", "page-001.json", _page(legalSummary="second"))

    index, stats = main.collect_reviewed_analysis(tmp_path)
    assert stats["discovered"] == 2
    assert stats["indexed"] == 1
    assert stats["duplicates"] == 1
    # The kept fallback record is the first path (sec-a).
    assert index["fallback"][("sub-a", "doc-a", 1)]["data"]["legalSummary"] == "first"


def test_collect_indexes_fallback_only_when_section_slug_missing(tmp_path):
    # Missing sectionSlug -> exact key is None but fallback key is valid, so
    # the page is still indexed (under fallback only).
    page = _page()
    del page["sectionSlug"]
    _write_page(tmp_path, "sub-a", "doc-a", "sec-a", "page-001.json", page)

    index, stats = main.collect_reviewed_analysis(tmp_path)
    assert stats["indexed"] == 1
    assert index["exact"] == {}
    assert ("sub-a", "doc-a", 1) in index["fallback"]


def test_collect_empty_corpus(tmp_path):
    index, stats = main.collect_reviewed_analysis(tmp_path)
    assert stats == {"discovered": 0, "indexed": 0, "invalid": 0, "duplicates": 0, "unmatched": 0}
    assert index == {"exact": {}, "fallback": {}}


# ---------------------------------------------------------------------------
# apply_preserved_analysis
# ---------------------------------------------------------------------------

STAMP = "2026-06-16T00:00:00+00:00"


def _index_from(old):
    record = {"data": old, "path": "x"}
    idx = {"exact": {}, "fallback": {}}
    ek = main.preservation_exact_key(old)
    fk = main.preservation_fallback_key(old)
    if ek is not None:
        idx["exact"][ek] = record
    if fk is not None:
        idx["fallback"][fk] = record
    return idx


def test_apply_exact_match_copies_only_whitelisted_fields():
    old = _page(legalSummary="kept summary", keyFacts=["a", "b"])
    # A field that is NOT in the preserve whitelist must not be carried over.
    old["sourcePageText"] = "should not be copied"
    index = _index_from(old)

    fresh = _page(legalSummary="", keyFacts=[], reviewedBy="")  # regenerated stub
    fresh.pop("reviewedBy")
    applied = main.apply_preserved_analysis(fresh, index, STAMP)

    assert applied is True
    assert fresh["legalSummary"] == "kept summary"
    assert fresh["keyFacts"] == ["a", "b"]
    assert fresh["reviewedBy"] == "jwogrady"
    assert "sourcePageText" not in fresh
    assert fresh["needsReview"] is False
    assert fresh["preservedFromReview"] is True
    assert fresh["preservedMatch"] == "exact"
    assert fresh["preservedAt"] == STAMP
    assert fresh["preservedSourcePageNumber"] == 1
    assert set(fresh["preservedFields"]) == {"legalSummary", "keyFacts", "reviewedBy"}


def test_apply_falls_back_when_section_slug_changed():
    old = _page(sectionSlug="old-sec", legalSummary="survives re-sectioning")
    index = _index_from(old)

    # Re-sectioning changed the sectionSlug, so the exact key won't hit; the
    # same-document/same-source-page fallback should.
    fresh = _page(sectionSlug="new-sec", legalSummary="")
    applied = main.apply_preserved_analysis(fresh, index, STAMP)

    assert applied is True
    assert fresh["preservedMatch"] == "fallback"
    assert fresh["legalSummary"] == "survives re-sectioning"


def test_apply_returns_false_without_index():
    fresh = _page(legalSummary="")
    assert main.apply_preserved_analysis(fresh, None, STAMP) is False
    assert main.apply_preserved_analysis(fresh, {}, STAMP) is False
    assert "preservedFromReview" not in fresh


def test_apply_returns_false_on_no_match():
    old = _page(documentSlug="other-doc")
    index = _index_from(old)
    fresh = _page(legalSummary="")  # different document -> no key hit
    assert main.apply_preserved_analysis(fresh, index, STAMP) is False


def test_apply_guard_refuses_cross_document_even_if_miskeyed():
    # Belt-and-braces: deliberately mis-key a record so the exact-key lookup
    # hits, but the stored data is for a different document. It must refuse.
    fresh = _page()
    ek = main.preservation_exact_key(fresh)
    miskeyed = {"data": _page(documentSlug="WRONG"), "path": "x"}
    index = {"exact": {ek: miskeyed}, "fallback": {}}

    assert main.apply_preserved_analysis(fresh, index, STAMP) is False
