"""Core corpus data models and the slug helper that keys them.

A SectionBoundary is a proposed logical part of one source PDF; a PdfEntry is
one Document/Source PDF inside the Archive. Both carry the slugs/IDs needed to
walk back up the archive -> submission -> document -> section -> page chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from slugify import slugify


@dataclass
class SectionBoundary:
    """A proposed logical section of a Document / Source PDF.

    start_page/end_page are 1-based page numbers in the original source PDF —
    the citable sourcePageNumber space. Boundaries always cover 1..pageCount
    with no gaps or overlaps; no pages are dropped.
    """

    title: str
    slug: str
    start_page: int
    end_page: int
    confidence: float
    reason: str
    detection_tier: str
    document_family: str = ""

    @property
    def page_count(self) -> int:
        return self.end_page - self.start_page + 1


@dataclass
class PdfEntry:
    """One Document / Source PDF inside the Archive / Packet.

    Until submissions are curated, each source PDF is assumed to be its own
    Submission, so submission_slug == document_slug. Future features may
    group multiple documents under one submission.
    """

    zip_path: str
    filename: str
    page_count: int | None  # None when the PDF is unreadable
    sha256: str | None
    submission_slug: str
    document_slug: str
    error: str = ""
    sections: list[SectionBoundary] = field(default_factory=list)


def unique_slug(base: str, fallback: str, used: set[str]) -> str:
    """Stable slugs: duplicate source stems must not collide."""
    slug = slugify(base) or fallback
    if slug in used:
        slug = f"{slug}-{fallback}"
    used.add(slug)
    return slug
