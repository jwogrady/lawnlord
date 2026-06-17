"""Provider adapters: parse a court-records *intake provider folder* into a
typed, in-memory case model — the curated source of truth that feeds identity,
parties, the docket, and the document set.

An intake folder is named for its **source provider** (the first is ``ody`` =
**Odyssey**, ``odyssey.mctx.org``). The provider name selects the adapter, so
future providers plug in without touching the model. An Odyssey export holds
four metadata JSON files plus a ``filings/`` folder of source PDFs:

    case-summary.json          identity header (caseNumber, title, court, …)
    case-history.json          parties + the phase-ordered docket timeline
    register-of-actions.json   the raw docket (parties, dispositions, events)
    filings.json               the document index (title, pageCount, file)

This layer does no I/O beyond reading those files, mints no IDs, and never
guesses: fields come straight from the curated JSON. Output is deterministic
(stable ordering) so callers can rely on it as a pure function of the folder.
The full cross-source docket reconciliation (timeline + register-of-actions +
filings.json) is deferred to the DuckDB ingest milestone; here the authoritative
event spine is ``case-history.timeline`` (the richest, phase-tagged source).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from slugify import slugify

# Intake metadata filenames (within a provider folder).
CASE_SUMMARY_FILENAME = "case-summary.json"
CASE_HISTORY_FILENAME = "case-history.json"
REGISTER_OF_ACTIONS_FILENAME = "register-of-actions.json"
FILINGS_FILENAME = "filings.json"
FILINGS_DIRNAME = "filings"


@dataclass(frozen=True)
class Attorney:
    """An attorney of record for a party."""

    name: str
    status: str = ""
    phone: str = ""


@dataclass(frozen=True)
class Party:
    """A party to the case (curated from the intake metadata)."""

    role: str
    name: str
    representation: str = ""  # e.g. "Pro Se"; empty when represented by counsel
    location: str = ""
    attorneys: tuple[Attorney, ...] = ()


@dataclass(frozen=True)
class Event:
    """A docket event from the phase-ordered case-history timeline."""

    date: str  # ISO (YYYY-MM-DD) as published by the provider
    phase: str
    event: str
    description: str = ""
    party: str = ""
    files: tuple[str, ...] = ()  # intake-relative paths, e.g. "filings/Foo.pdf"


@dataclass(frozen=True)
class DocumentRef:
    """A reference to one source PDF, curated from filings.json.

    ``declared_page_count`` is what the provider reports; the exploder reads the
    actual count later and a downstream step cross-checks the two.
    """

    intake_path: str  # "filings/Foo.pdf"
    filename: str  # "Foo.pdf"
    title: str  # filings.json "image"
    declared_page_count: int | None = None
    docket_event: str = ""  # filings.json "event"
    filing_date: str = ""  # filings.json "date"


@dataclass(frozen=True)
class CaseIdentity:
    """The case header, combined from case-summary + case-history."""

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


@dataclass(frozen=True)
class CaseModel:
    """The parsed, in-memory model of one case from a provider folder."""

    provider: str
    identity: CaseIdentity
    parties: tuple[Party, ...] = ()
    events: tuple[Event, ...] = ()
    documents: tuple[DocumentRef, ...] = ()


def _load_json(path: Path) -> dict:
    """Read a JSON object, or return {} when the file is absent, unreadable,
    malformed, or not a JSON object — tolerant of imperfect provider exports."""
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _first(*values: str | None) -> str:
    """First non-empty string among the arguments, else ""."""
    for value in values:
        if value:
            return value
    return ""


def _parse_attorneys(raw: list | None) -> tuple[Attorney, ...]:
    return tuple(
        Attorney(
            name=a.get("name", ""),
            status=a.get("status", ""),
            phone=a.get("phone", ""),
        )
        for a in (raw or [])
        if isinstance(a, dict)
    )


def _parse_parties(raw: list | None) -> tuple[Party, ...]:
    return tuple(
        Party(
            role=p.get("role", ""),
            name=p.get("name", ""),
            representation=p.get("representation", ""),
            location=p.get("location", ""),
            attorneys=_parse_attorneys(p.get("attorneys")),
        )
        for p in (raw or [])
        if isinstance(p, dict)
    )


def _parse_events(timeline: list | None) -> tuple[Event, ...]:
    return tuple(
        Event(
            date=e.get("date", ""),
            phase=e.get("phase", ""),
            event=e.get("event", ""),
            description=e.get("description", ""),
            party=e.get("party", ""),
            files=tuple(e.get("files", []) or []),
        )
        for e in (timeline or [])
        if isinstance(e, dict)
    )


def _parse_documents(filings: dict) -> tuple[DocumentRef, ...]:
    """Documents from filings.json, deduplicated by file path (first wins),
    sorted by intake path for deterministic output. A document can be listed
    under several docket events; here it collapses to one reference."""
    by_path: dict[str, DocumentRef] = {}
    for key in ("selectedEvent", "otherEventsOnThisCase", "otherImagesOnThisCase"):
        for row in filings.get(key, []) or []:
            if not isinstance(row, dict):
                continue
            path = row.get("file", "")
            if not path or path in by_path:
                continue
            by_path[path] = DocumentRef(
                intake_path=path,
                filename=Path(path).name,
                title=row.get("image", ""),
                declared_page_count=row.get("pageCount"),
                docket_event=row.get("event", ""),
                filing_date=row.get("date", ""),
            )
    return tuple(by_path[path] for path in sorted(by_path))


def _parse_identity(summary: dict, history: dict) -> CaseIdentity:
    """Combine the identity header, preferring the richer case-history fields
    and falling back to case-summary; nothing is invented."""
    disposition = history.get("disposition", {}) or {}
    return CaseIdentity(
        case_number=_first(history.get("caseNumber"), summary.get("caseNumber")),
        title=_first(history.get("caseTitle"), summary.get("caseTitle")),
        court=_first(history.get("court"), summary.get("location")),
        judicial_officer=history.get("judicialOfficer", ""),
        case_type=_first(history.get("caseType"), summary.get("caseType")),
        status=_first(history.get("status"), summary.get("status")),
        date_filed=_first(history.get("dateFiled"), summary.get("dateFiled")),
        disposition_type=disposition.get("type", ""),
        disposition_date=disposition.get("date", ""),
        source_url=_first(history.get("sourceUrl"), summary.get("sourceUrl")),
    )


def parse_odyssey(intake_dir: str | Path) -> CaseModel:
    """Parse an Odyssey (`ody`) provider export folder into a CaseModel.

    Tolerant of absent files (each contributes what it has). Parties come from
    case-history (richest, with attorneys), falling back to register-of-actions;
    the event spine is case-history's phase-tagged timeline; documents come from
    filings.json, deduplicated by file path.
    """
    intake_dir = Path(intake_dir)
    summary = _load_json(intake_dir / CASE_SUMMARY_FILENAME)
    history = _load_json(intake_dir / CASE_HISTORY_FILENAME)
    register = _load_json(intake_dir / REGISTER_OF_ACTIONS_FILENAME)
    filings = _load_json(intake_dir / FILINGS_FILENAME)

    parties = _parse_parties(history.get("parties") or register.get("parties"))

    return CaseModel(
        provider=intake_dir.name,
        identity=_parse_identity(summary, history),
        parties=parties,
        events=_parse_events(history.get("timeline")),
        documents=_parse_documents(filings),
    )


# Provider folder name -> adapter. Aliases keep the selector forgiving.
PROVIDERS = {
    "ody": parse_odyssey,
    "odyssey": parse_odyssey,
}


def parse_provider(provider: str, intake_dir: str | Path) -> CaseModel:
    """Dispatch to the adapter for ``provider`` (the intake folder name).

    Unknown providers fall back to the Odyssey adapter — currently the only
    schema — rather than failing, so a differently-named folder holding an
    Odyssey export still parses.
    """
    adapter = PROVIDERS.get(provider.lower(), parse_odyssey)
    return adapter(intake_dir)


def case_slug(case_number: str) -> str:
    """Filesystem-safe slug for a case, derived from its number (not the
    provider folder name). ``"25-09-14566"`` stays ``"25-09-14566"``."""
    return slugify(case_number) or "case"
