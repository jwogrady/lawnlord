"""Section-boundary detection: the four-tier dispatcher and its helpers.

Boundaries are metadata-only proposals (1-based source-PDF page ranges always
covering 1..N with no gaps/overlaps), in priority order: manual overrides,
PDF bookmarks, hardened legal-heading scan, whole-PDF fallback. Tune the
heading-shape helpers and LEGAL_BOUNDARY_PATTERNS here, not the dispatcher,
when changing what counts as a section heading.
"""

from __future__ import annotations

import json
import re

import fitz
from slugify import slugify

from .console import console
from .models import SectionBoundary
from .paths import FILINGS_DIR, MANUAL_BOUNDARIES_FILENAME

# Pattern -> documentFamily. More specific patterns first so family
# inference picks "certificate-of-service" over "notice" etc. Any match
# qualifies a heading-shaped line as a section boundary.
LEGAL_BOUNDARY_PATTERNS: list[tuple[str, str]] = [
    (r"\bCERTIFICATE OF SERVICE\b", "certificate-of-service"),
    (r"\bEXHIBIT\s+[A-Z0-9]+\b", "exhibit"),
    (r"\bMOTION\b", "motion"),
    (r"\bORDER\b", "order"),
    (r"\bNOTICE\b", "notice"),
    (r"\bRESPONSE\b", "response"),
    (r"\bREPLY\b", "reply"),
    (r"\bAFFIDAVIT\b", "affidavit"),
    (r"\bDECLARATION\b", "declaration"),
    (r"\bCOMPLAINT\b", "complaint"),
    (r"\bPETITION\b", "petition"),
    (r"\bANSWER\b", "answer"),
    (r"\bMEMORANDUM\b", "memorandum"),
    (r"\bBRIEF\b", "brief"),
    (r"\bJUDGMENT\b", "judgment"),
    (r"\bSUBPOENA\b", "subpoena"),
]

# Heading scan window: legal caption blocks (cause number, parties, court)
# push the document title 15-25 non-empty lines down on page 1.
HEADING_SCAN_LINES = 30
HEADING_MAX_CHARS = 90
HEADING_MAX_WORDS = 12

# Words allowed lowercase inside a title-case heading.
HEADING_MINOR_WORDS = {"a", "an", "and", "by", "for", "in", "of", "on", "or", "the", "to", "v", "vs"}

# A real heading doesn't end mid-thought on a connective word.
HEADING_DANGLING_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "that", "the", "to", "with",
}

CONFIDENCE_MANUAL = 1.0
CONFIDENCE_BOOKMARK = 0.95
CONFIDENCE_HEADING = 0.65
CONFIDENCE_FRONT_MATTER = 0.60
CONFIDENCE_UNTRUSTED_BOOKMARK = 0.60
CONFIDENCE_FALLBACK = 0.50

# Bookmark titles that are filenames (e.g. "...statement-fees.pdf") are merge
# artifacts inherited from combined source PDFs, not real section titles —
# the boundary may still be right, but a human must confirm it.
FILENAME_LIKE_BOOKMARK_RE = re.compile(
    r"\.(pdf|docx?|xlsx?|csv|txt|eml|msg|jpe?g|png|tiff?)\s*$", re.IGNORECASE
)

# Any proposed section below this needs a human to confirm the boundary.
REVIEW_CONFIDENCE_THRESHOLD = 0.9

TIER_MANUAL = "manual"
TIER_BOOKMARKS = "bookmarks"
TIER_HEADING_SCAN = "heading-scan"
TIER_FALLBACK = "fallback"


def get_page_text(doc: fitz.Document, page_index: int) -> str:
    try:
        return doc[page_index].get_text("text") or ""
    except Exception:
        return ""


def normalize_heading_candidate(line: str) -> str:
    """Collapse whitespace and strip decoration so heading checks see the line
    the way a reader would."""
    line = re.sub(r"\s+", " ", line).strip()
    return line.strip("·•|_ ").strip()


def uppercase_letter_ratio(line: str) -> float:
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def is_probable_heading_line(line: str) -> bool:
    """Heading-shaped: short, starts upper, free of prose punctuation, and
    either mostly uppercase or consistently title-case. This is what keeps a
    MOTION/ORDER/NOTICE keyword buried in body prose from becoming a boundary."""
    if not (4 <= len(line) <= HEADING_MAX_CHARS):
        return False

    words = line.split()
    if len(words) > HEADING_MAX_WORDS:
        return False
    if line[0].islower():
        return False
    if line[-1] in ",;:-—":
        return False
    if words[-1].lower().strip(".,;:") in HEADING_DANGLING_WORDS:
        return False
    # A sentence boundary mid-line reads as prose, not a heading.
    if re.search(r"[a-z]{2}[.;:]\s", line):
        return False

    if uppercase_letter_ratio(line) >= 0.7:
        return True

    tokens = re.findall(r"[A-Za-z][A-Za-z'’\-]*", line)
    return bool(tokens) and all(
        t[0].isupper() or t.lower() in HEADING_MINOR_WORDS for t in tokens
    )


def legal_keyword_family(text: str) -> str | None:
    """documentFamily for the first legal keyword in text, or None."""
    upper = text.upper()
    for pattern, family in LEGAL_BOUNDARY_PATTERNS:
        if re.search(pattern, upper):
            return family
    return None


def find_heading_boundary(page_text: str) -> tuple[str, bool] | None:
    """Return (heading line, is_strong) for the first plausible legal heading
    near the top of a page, or None. Strong means fully uppercase — the
    classic styled legal title (FINAL SUMMARY JUDGMENT, EXHIBIT A)."""
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]

    for raw in lines[:HEADING_SCAN_LINES]:
        candidate = normalize_heading_candidate(raw)
        if not is_probable_heading_line(candidate):
            continue
        if legal_keyword_family(candidate) is not None:
            return candidate, uppercase_letter_ratio(candidate) >= 0.9

    return None


def clean_title(text: str, fallback: str) -> str:
    """Best-available title from page text: prefer a legal-keyword line, then
    any substantial line, then the fallback."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for line in lines[:40]:
        if legal_keyword_family(line) is not None:
            return line[:140]

    for line in lines[:10]:
        # Ruled lines ("________") and other letterless decoration make
        # useless titles and slugify to nothing.
        if len(line) > 8 and any(c.isalpha() for c in line):
            return line[:140]

    return fallback


def load_manual_boundaries() -> dict:
    """Load optional src/filings/bundle-boundaries.json manual boundaries (Tier 1).

    The file is the committed source of truth for section boundaries; it is
    simply honored when present. Returns {} when absent or unparseable.
    """
    path = FILINGS_DIR / MANUAL_BOUNDARIES_FILENAME
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level must be an object keyed by source PDF name")
    except Exception as exc:
        console.print(
            f"[red]Could not parse {path}: {exc} — ignoring manual boundaries.[/]"
        )
        return {}

    console.print(f"[bold]Manual boundaries:[/] {path}")
    return data


def manual_entries_for(
    manual_boundaries: dict, source_zip_path: str, pdf_name: str
) -> list | None:
    """Manual boundaries are keyed by sourceZipPath or original filename —
    either at the top level or under a "documents" wrapper (the Feature 8
    template shape) — and each value may be a bare list of section entries
    or an object wrapping them in a "sections" key. Extra fields are
    ignored."""
    scopes = [manual_boundaries]
    documents = manual_boundaries.get("documents")
    if isinstance(documents, dict):
        scopes.append(documents)
    for scope in scopes:
        value = scope.get(source_zip_path)
        if value is None:
            value = scope.get(pdf_name)
        if isinstance(value, dict):
            value = value.get("sections")
        if isinstance(value, list):
            return value
    return None


def covers_exactly(sections: list[SectionBoundary], page_count: int) -> bool:
    """True when sections cover 1..page_count with no gaps or overlaps."""
    expected = 1
    for s in sorted(sections, key=lambda s: s.start_page):
        if s.start_page != expected or s.end_page < s.start_page:
            return False
        expected = s.end_page + 1
    return expected == page_count + 1


def finalize_slugs(sections: list[SectionBoundary]) -> list[SectionBoundary]:
    """Section slugs must be unique within their document."""
    used: set[str] = set()
    for i, s in enumerate(sections, start=1):
        base = slugify(s.title) or f"section-{i:03d}"
        slug = base if base not in used else f"{base}-p{s.start_page}"
        used.add(slug)
        s.slug = slug
    return sections


def sections_from_manual(
    entries: list, page_count: int, pdf_name: str
) -> list[SectionBoundary]:
    sections: list[SectionBoundary] = []

    for i, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            console.print(
                f"[red]Warning:[/] manual boundary entry {i} for {pdf_name}"
                " is not an object; skipped"
            )
            continue
        try:
            start = int(entry["startPage"])
            end = int(entry["endPage"])
        except (KeyError, TypeError, ValueError):
            console.print(
                f"[red]Warning:[/] invalid manual boundary entry {i} for {pdf_name}; skipped"
            )
            continue

        if not (1 <= start <= end <= page_count):
            console.print(
                f"[red]Warning:[/] manual boundary {start}-{end} out of range"
                f" for {pdf_name} ({page_count} pages); skipped"
            )
            continue

        title = str(entry.get("title") or f"Section {i}")
        sections.append(
            SectionBoundary(
                title=title,
                slug="",
                start_page=start,
                end_page=end,
                confidence=CONFIDENCE_MANUAL,
                reason=f"Manual boundary ({MANUAL_BOUNDARIES_FILENAME})",
                detection_tier=TIER_MANUAL,
                document_family=str(entry.get("documentFamily") or ""),
            )
        )

    return sections


def build_sections(
    starts: list[tuple[int, str, float, str, str]], page_count: int
) -> list[SectionBoundary]:
    """Turn sorted, deduplicated (page, title, confidence, reason, tier)
    section starts into contiguous boundaries covering every page."""
    sections: list[SectionBoundary] = []

    for i, (start, title, confidence, reason, tier) in enumerate(starts):
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else page_count
        if start > end:
            continue
        section_title = title or f"Section {i + 1}"
        sections.append(
            SectionBoundary(
                title=section_title,
                slug="",
                start_page=start,
                end_page=end,
                confidence=confidence,
                reason=reason,
                detection_tier=tier,
                document_family=legal_keyword_family(section_title) or "",
            )
        )

    return finalize_slugs(sections)


def detect_sections_in_doc(
    doc: fitz.Document, pdf_name: str, pdf_stem: str, manual_entries: list | None = None
) -> list[SectionBoundary]:
    """Propose section boundaries for one source PDF.

    Tiers, in priority order: manual overrides, PDF bookmarks/outline,
    hardened legal-heading scan, whole-PDF conservative fallback. Every tier
    guarantees full 1..N page coverage with no gaps or overlaps.
    """
    page_count = doc.page_count
    if page_count == 0:
        return []

    # Tier 1: manual boundaries always win — they encode human review.
    if manual_entries:
        manual = sections_from_manual(manual_entries, page_count, pdf_name)
        if manual and covers_exactly(manual, page_count):
            return finalize_slugs(sorted(manual, key=lambda s: s.start_page))
        if manual:
            console.print(
                f"[red]Warning:[/] manual boundaries for {pdf_name} do not cover"
                f" pages 1-{page_count} without gaps/overlaps; falling back to detection."
            )
        else:
            console.print(
                f"[yellow]No usable manual boundaries for {pdf_name};"
                " falling back to detection.[/]"
            )

    # Tier 2: PDF bookmarks/outline. Top-level entries are section starts.
    toc = doc.get_toc(simple=True)
    if toc:
        starts: list[tuple[int, str, float, str, str]] = []
        seen_pages: set[int] = set()

        for level, title, page_num in sorted(toc, key=lambda t: t[2]):
            if level != 1:
                continue
            if not (1 <= page_num <= page_count) or page_num in seen_pages:
                continue
            seen_pages.add(page_num)
            clean = title.strip()
            if FILENAME_LIKE_BOOKMARK_RE.search(clean):
                starts.append(
                    (
                        page_num,
                        clean,
                        CONFIDENCE_UNTRUSTED_BOOKMARK,
                        "PDF bookmark with filename-like title (merge artifact; needs review)",
                        TIER_BOOKMARKS,
                    )
                )
            else:
                starts.append(
                    (page_num, clean, CONFIDENCE_BOOKMARK, "PDF bookmark / outline", TIER_BOOKMARKS)
                )

        # Pages before the first bookmark must not be silently dropped —
        # every source page belongs to some section (chain of custody).
        if starts and starts[0][0] > 1:
            front_title = clean_title(get_page_text(doc, 0), f"{pdf_stem} front matter")
            starts.insert(
                0,
                (1, front_title, CONFIDENCE_FRONT_MATTER, "Pages before first PDF bookmark", TIER_BOOKMARKS),
            )

        if starts:
            return build_sections(starts, page_count)

    # Tier 3: hardened legal heading scan. A boundary requires a
    # heading-shaped line carrying a legal keyword near the top of a page —
    # a keyword buried in body prose is not enough.
    starts = []
    strong_heading_pages: set[int] = set()

    for idx in range(page_count):
        found = find_heading_boundary(get_page_text(doc, idx))
        if found is None:
            continue
        heading, strong = found
        page_num = idx + 1
        starts.append(
            (
                page_num,
                heading[:140],
                CONFIDENCE_HEADING,
                f"Matched legal heading: {heading[:120]}",
                TIER_HEADING_SCAN,
            )
        )
        if strong:
            strong_heading_pages.add(page_num)

    # Tier 7, conservative fallback: coverage must start at page 1 even when
    # nothing (or nothing on page 1) matched.
    if not starts or starts[0][0] != 1:
        title = clean_title(get_page_text(doc, 0), pdf_stem)
        reason = (
            "No section boundaries detected; whole PDF as one section"
            if not starts
            else "Pages before first detected heading"
        )
        starts.insert(0, (1, title, CONFIDENCE_FALLBACK, reason, TIER_FALLBACK))

    seen_pages = set()
    deduped: list[tuple[int, str, float, str, str]] = []
    for item in sorted(starts):
        if item[0] in seen_pages:
            continue
        seen_pages.add(item[0])
        deduped.append(item)

    # Conservative merge: a weak (not fully-uppercase) heading that would
    # yield a one-page section is more likely styled prose than a real
    # sub-document — absorb it into the preceding section. Strong all-caps
    # headings (EXHIBIT A, CERTIFICATE OF SERVICE) stand alone.
    # Manual/bookmark sections never reach this pass.
    kept: list[tuple[int, str, float, str, str]] = []
    for i, item in enumerate(deduped):
        page = item[0]
        next_page = deduped[i + 1][0] if i + 1 < len(deduped) else page_count + 1
        single_page = next_page - page == 1
        weak_heading = item[4] == TIER_HEADING_SCAN and page not in strong_heading_pages
        if kept and single_page and weak_heading:
            continue
        kept.append(item)

    return build_sections(kept, page_count)


def section_summary(section: SectionBoundary, index: int, document_sha: str) -> dict:
    # Provisional sectionId: anchored to the document content hash and the
    # source page range, so it is stable across re-runs while boundaries are
    # unchanged — and changes when a boundary moves (it describes different
    # pages, so it IS a different section).
    section_id = f"sec_{document_sha[:12]}_p{section.start_page:03d}-p{section.end_page:03d}"
    # Field names match section metadata.json (sourcePageStart/sourcePageEnd/
    # boundaryConfidence) so every SPA-facing JSON view uses one vocabulary.
    return {
        "sectionIndex": index,
        "sectionId": section_id,
        "title": section.title,
        "sectionSlug": section.slug,
        "sourcePageStart": section.start_page,
        "sourcePageEnd": section.end_page,
        "pageCount": section.page_count,
        "boundaryConfidence": section.confidence,
        "reason": section.reason,
        "detectionTier": section.detection_tier,
        "documentFamily": section.document_family,
        "needsHumanReview": section.confidence < REVIEW_CONFIDENCE_THRESHOLD,
    }


def confidence_distribution(sections: list[SectionBoundary]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for s in sections:
        key = f"{s.confidence:.2f}"
        dist[key] = dist.get(key, 0) + 1
    return dict(sorted(dist.items(), reverse=True))
