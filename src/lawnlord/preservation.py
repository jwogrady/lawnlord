"""--force review preservation.

Before a forced rebuild deletes a submission folder, reviewed page analysis
(needsReview exactly false) is indexed by collect_reviewed_analysis() and
re-applied onto the regenerated stubs by apply_preserved_analysis(). Only the
human-editable legal-analysis and review-metadata fields move; provenance,
paths, and citations are always regenerated fresh.
"""

from __future__ import annotations

import json
from pathlib import Path

# Human-editable legal-analysis fields carried over from a reviewed page
# analysis JSON when --force regenerates its stub. Must stay in sync with
# legal_analysis_placeholders().
PRESERVED_LEGAL_FIELDS = (
    "legalSummary",
    "keyFacts",
    "dates",
    "deadlines",
    "people",
    "organizations",
    "parties",
    "attorneys",
    "judges",
    "caseNumbers",
    "statutesOrRulesCited",
    "casesCited",
    "exhibitsReferenced",
    "claims",
    "defenses",
    "arguments",
    "reliefRequested",
    "ordersOrRulings",
    "timelineEvents",
    "tags",
    "notes",
)

# Optional review metadata also carried over when present.
PRESERVED_REVIEW_METADATA_FIELDS = (
    "reviewedBy",
    "reviewedAt",
    "reviewNotes",
    "confidence",
)


def is_reviewed_analysis(data: dict) -> bool:
    """A page analysis is human-reviewed only when needsReview is exactly
    false. True, missing, or any other value means unreviewed."""
    return data.get("needsReview") is False


def preservation_exact_key(data: dict) -> tuple | None:
    """Strict identity for a reviewed page: same archive, submission,
    document, section, and source page. None if any part is missing."""
    parts = (
        data.get("archiveId"),
        data.get("submissionSlug"),
        data.get("documentSlug"),
        data.get("sectionSlug"),
        data.get("sourcePageNumber"),
    )
    if any(part is None for part in parts):
        return None
    return parts


def preservation_fallback_key(data: dict) -> tuple | None:
    """Relaxed identity that survives re-sectioning: manual boundary changes
    may alter sectionSlug while the same source page of the same document in
    the same submission remains reviewed. Never crosses documents or source
    pages. None if any part is missing."""
    parts = (
        data.get("submissionSlug"),
        data.get("documentSlug"),
        data.get("sourcePageNumber"),
    )
    if any(part is None for part in parts):
        return None
    return parts


def collect_reviewed_analysis(corpus_dir: Path) -> tuple[dict, dict]:
    """Scan the existing corpus for reviewed page analysis JSON before a
    forced rebuild deletes it.

    Returns (index, stats). The index maps exact and fallback keys to
    {"data": ..., "path": ...} records for every parseable analysis file
    whose needsReview is exactly false. Invalid JSON is counted and skipped
    without crashing. Duplicate keys keep the first file in sorted path
    order; later claimants are counted as duplicates and skipped. Reviewed
    files lacking the identity fields for both keys are counted as unmatched
    and not preserved.
    """
    index: dict = {"exact": {}, "fallback": {}}
    stats = {
        "discovered": 0,
        "indexed": 0,
        "invalid": 0,
        "duplicates": 0,
        "unmatched": 0,
    }

    for path in sorted(
        corpus_dir.glob("submissions/*/documents/*/sections/*/analysis/page-*.json")
    ):
        stats["discovered"] += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stats["invalid"] += 1
            continue
        if not isinstance(data, dict) or not is_reviewed_analysis(data):
            continue

        record = {"data": data, "path": str(path)}
        exact_key = preservation_exact_key(data)
        fallback_key = preservation_fallback_key(data)
        if exact_key is None and fallback_key is None:
            # Reviewed but missing the identity fields for both keys: it can
            # never be matched to a regenerated page, so it cannot be
            # preserved. Counted so the loss is visible, not silent.
            stats["unmatched"] += 1
            continue
        indexed = False
        duplicate = False

        if exact_key is not None:
            if exact_key in index["exact"]:
                duplicate = True
            else:
                index["exact"][exact_key] = record
                indexed = True
        if fallback_key is not None:
            if fallback_key in index["fallback"]:
                duplicate = True
            else:
                index["fallback"][fallback_key] = record
                indexed = True

        if indexed:
            stats["indexed"] += 1
        elif duplicate:
            stats["duplicates"] += 1

    return index, stats


def apply_preserved_analysis(
    page_analysis: dict, preservation_index: dict | None, generated_at: str
) -> bool:
    """Re-apply a previously reviewed analysis onto a freshly generated page
    stub. Tries the exact key first, then the same-document/source-page
    fallback. Only human-editable legal-analysis fields and review metadata
    are copied; provenance/path/citation fields stay as freshly generated.
    Returns True when preservation happened."""
    if not preservation_index:
        return False

    record = None
    match = None
    exact_key = preservation_exact_key(page_analysis)
    if exact_key is not None:
        record = preservation_index.get("exact", {}).get(exact_key)
        if record is not None:
            match = "exact"
    if record is None:
        fallback_key = preservation_fallback_key(page_analysis)
        if fallback_key is not None:
            record = preservation_index.get("fallback", {}).get(fallback_key)
            if record is not None:
                match = "fallback"
    if record is None:
        return False

    old = record["data"]
    # Belt and braces: never preserve across documents or source pages even
    # if an index entry were somehow mis-keyed.
    if old.get("documentSlug") != page_analysis.get("documentSlug"):
        return False
    if old.get("sourcePageNumber") != page_analysis.get("sourcePageNumber"):
        return False

    preserved_fields: list[str] = []
    for field_name in PRESERVED_LEGAL_FIELDS + PRESERVED_REVIEW_METADATA_FIELDS:
        if field_name in old:
            page_analysis[field_name] = old[field_name]
            preserved_fields.append(field_name)

    page_analysis["needsReview"] = False
    page_analysis["preservedFromReview"] = True
    page_analysis["preservedAt"] = generated_at
    page_analysis["preservedSourcePageNumber"] = old.get("sourcePageNumber")
    page_analysis["preservedMatch"] = match
    page_analysis["preservedFields"] = preserved_fields
    return True
