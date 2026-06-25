"""Core corpus data models and the slug helper that keys them.

A SectionBoundary is a proposed logical part of one source PDF; a PdfEntry is
one Document/Source PDF inside the Archive. Both carry the slugs/IDs needed to
walk back up the archive -> submission -> document -> section -> page chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from slugify import slugify

# Intake layout constant: the filed PDFs live under this dir inside the zip.
# The zip standard uses ``files/`` (the old provider layout used ``filings/``).
FILES_DIRNAME = "files"


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
    # Absolute path to the PDF on disk when the source is a folder of loose
    # PDFs (folder mode). Empty for ZIP mode, where bytes come from the archive.
    source_path: str = ""


def unique_slug(base: str, fallback: str, used: set[str]) -> str:
    """Stable slugs: duplicate source stems must not collide."""
    slug = slugify(base) or fallback
    if slug in used:
        slug = f"{slug}-{fallback}"
    used.add(slug)
    return slug


def case_slug(case_number: str) -> str:
    """Filesystem-safe slug for a case, derived from its number.
    ``"25-09-14566"`` stays ``"25-09-14566"``."""
    return slugify(case_number) or "case"


def is_suspicious_entry(name: str) -> bool:
    """Flag zip entries that would escape an extraction root (path traversal).
    Needed for safe extraction of the zip's ``files/`` PDFs."""
    pure = PurePosixPath(name.replace("\\", "/"))
    return pure.is_absolute() or ".." in pure.parts


# ---------------------------------------------------------------------------
# Case data contract
#
# The in-memory model of one case. Previously produced by provider adapters;
# now the single shape the zip-standard reader (next branch) populates from the
# deterministic ``data.json``. The DuckDB ingest consumes this model verbatim.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Attorney:
    """An attorney of record for a party."""

    name: str
    status: str = ""
    phone: str = ""
    number: str = ""


@dataclass(frozen=True)
class Party:
    """A party to the case."""

    role: str
    name: str
    representation: str = ""  # e.g. "Pro Se"; empty when represented by counsel
    location: str = ""
    attorneys: tuple[Attorney, ...] = ()
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Event:
    """A docket event from the register of actions / case timeline."""

    date: str  # ISO (YYYY-MM-DD) or as published
    phase: str
    event: str
    description: str = ""
    party: str = ""
    files: tuple[str, ...] = ()  # intake-relative paths, e.g. "files/doc-1.pdf"


@dataclass(frozen=True)
class DocumentRef:
    """A reference to one filed PDF (a court "image")."""

    intake_path: str  # "files/doc-1.pdf"
    filename: str  # "doc-1.pdf"
    title: str  # data.json "Image"
    declared_page_count: int | None = None
    docket_event: str = ""  # data.json "event"
    filing_date: str = ""  # data.json "date"
    source_url: str = ""  # data.json per-document "url"; "" when absent


@dataclass(frozen=True)
class Hearing:
    """A scheduled hearing. ``result`` records the outcome."""

    date_time: str
    hearing_type: str = ""
    judge: str = ""
    location: str = ""
    result: str = ""


@dataclass(frozen=True)
class FinancialTransaction:
    """One line of the financial ledger."""

    date: str = ""
    description: str = ""
    amount: str = ""


@dataclass(frozen=True)
class Financials:
    """Money assessed/paid on the case, with the per-line ledger."""

    party: str = ""
    total_assessment: str = ""
    total_payments: str = ""
    balance_due: str = ""
    balance_as_of: str = ""
    transactions: tuple[FinancialTransaction, ...] = ()


@dataclass(frozen=True)
class DocketDocument:
    """A document named on a docket entry."""

    name: str
    declared_page_count: int | None = None
    intake_path: str = ""


@dataclass(frozen=True)
class DocketEntry:
    """One row of the register of actions, carrying any free-text comment and
    per-document page counts, including pure entries with no document."""

    date: str
    event: str = ""
    type: str = ""
    comment: str = ""
    documents: tuple[DocketDocument, ...] = ()


@dataclass(frozen=True)
class CaseIdentity:
    """The case header."""

    case_number: str
    title: str = ""
    court: str = ""
    judicial_officer: str = ""
    case_type: str = ""
    status: str = ""
    date_filed: str = ""
    disposition_type: str = ""
    disposition_date: str = ""
    source_url: str = ""
    citation_number: str = ""
    disposition_comment: str = ""
    disposition_judicial_officer: str = ""
    case_category: str = ""
    clerk: str = ""
    last_refreshed: str = ""


@dataclass(frozen=True)
class CaseModel:
    """The parsed, in-memory model of one case (from the zip's ``data.json``)."""

    provider: str
    identity: CaseIdentity
    parties: tuple[Party, ...] = ()
    events: tuple[Event, ...] = ()
    documents: tuple[DocumentRef, ...] = ()
    hearings: tuple[Hearing, ...] = ()
    financials: Financials | None = None
    docket: tuple[DocketEntry, ...] = ()
    case_flags: tuple[str, ...] = ()
    case_cross_references: tuple[str, ...] = ()
    source_note: str = ""
