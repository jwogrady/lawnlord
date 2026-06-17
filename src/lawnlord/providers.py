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

A reconciled ``combo`` folder additionally holds a re:SearchTX ``meta.json``;
its adapter (``parse_combo``) merges that in — attorney bar numbers, a hearings
table, the financial summary, and a docket of the registrar/judge's comments —
on top of the Odyssey base. The Odyssey ``case-history.timeline`` remains the
phase-tagged event spine; the merged ``docket`` is the richer parallel view.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from slugify import slugify

# Intake metadata filenames (within a provider folder).
CASE_SUMMARY_FILENAME = "case-summary.json"
CASE_HISTORY_FILENAME = "case-history.json"
REGISTER_OF_ACTIONS_FILENAME = "register-of-actions.json"
FILINGS_FILENAME = "filings.json"
FILINGS_DIRNAME = "filings"
# re:SearchTX (research.txcourts.gov) export, present in a reconciled `combo`
# folder alongside the Odyssey JSONs. Adds hearings, attorney bar numbers, and
# a docket with the judge's comments + per-document page counts.
RESEARCH_META_FILENAME = "meta.json"


def _norm(text: str) -> str:
    """Lowercase alphanumeric-only key for tolerant name/title matching."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


@dataclass(frozen=True)
class Attorney:
    """An attorney of record for a party.

    ``number`` is the State Bar of Texas attorney number, available from the
    re:SearchTX export (merged in for a ``combo`` intake)."""

    name: str
    status: str = ""
    phone: str = ""
    number: str = ""


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
class Hearing:
    """A scheduled hearing (from the re:SearchTX hearings table). ``result``
    records the outcome, e.g. "Canceled - Case Disposed"."""

    date_time: str
    hearing_type: str = ""
    judge: str = ""
    location: str = ""
    result: str = ""


@dataclass(frozen=True)
class Financials:
    """Money assessed/paid on the case (from the Odyssey financial summary)."""

    party: str = ""
    total_assessment: str = ""
    total_payments: str = ""
    balance_due: str = ""
    balance_as_of: str = ""


@dataclass(frozen=True)
class DocketDocument:
    """A document named on a docket entry. ``intake_path`` is joined from the
    file index when the name resolves to a known source PDF, else ""."""

    name: str
    declared_page_count: int | None = None
    intake_path: str = ""


@dataclass(frozen=True)
class DocketEntry:
    """One row of the re:SearchTX docket — the richest event source, carrying
    the registrar/judge's free-text comment (e.g. the grant/deny note) and
    per-document page counts, including pure docket entries with no document."""

    date: str
    event: str = ""
    type: str = ""
    comment: str = ""
    documents: tuple[DocketDocument, ...] = ()


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
    """The parsed, in-memory model of one case from a provider folder.

    ``events`` is the phase-ordered Odyssey timeline (the navigational spine).
    ``hearings``, ``financials``, and ``docket`` are populated only for a
    reconciled ``combo`` intake, which merges the re:SearchTX export: hearings
    (with results), the money summary, and the richer docket (free-text
    comments + page counts) whose document names are linked back to the file
    index. Attorney bar ``number``s are likewise merged onto ``parties``.
    """

    provider: str
    identity: CaseIdentity
    parties: tuple[Party, ...] = ()
    events: tuple[Event, ...] = ()
    documents: tuple[DocumentRef, ...] = ()
    hearings: tuple[Hearing, ...] = ()
    financials: Financials | None = None
    docket: tuple[DocketEntry, ...] = ()


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


def _meta_table_rows(meta: dict, key: str) -> list:
    """Rows of a re:SearchTX section that is shaped {columns, rows: [...]}."""
    section = meta.get(key)
    if not isinstance(section, dict):
        return []
    rows = section.get("rows")
    return rows if isinstance(rows, list) else []


def _parse_hearings(meta: dict) -> tuple[Hearing, ...]:
    return tuple(
        Hearing(
            date_time=r.get("dateTime", ""),
            hearing_type=r.get("hearingType", ""),
            judge=r.get("judge", "") or "",
            location=r.get("location", "") or "",
            result=r.get("result", "") or "",
        )
        for r in _meta_table_rows(meta, "hearings")
        if isinstance(r, dict)
    )


def _parse_financials(history: dict) -> Financials | None:
    """Money summary from the Odyssey financialInformation block (case-history,
    falling back to register-of-actions). None when absent."""
    fi = history.get("financialInformation")
    if not isinstance(fi, dict):
        return None
    balance = fi.get("balanceDueAsOf") or {}

    def s(value) -> str:
        # Stringify, but keep falsy-but-valid values like 0; None/absent -> "".
        return "" if value is None else str(value)

    return Financials(
        party=fi.get("party", ""),
        total_assessment=s(fi.get("totalFinancialAssessment")),
        total_payments=s(fi.get("totalPaymentsAndCredits")),
        balance_due=s(balance.get("amount")),
        balance_as_of=s(balance.get("date")),
    )


def _attorney_numbers(meta: dict) -> dict[str, str]:
    """Map normalized attorney name -> State Bar number, from meta.json parties."""
    numbers: dict[str, str] = {}
    for party in _meta_table_rows(meta, "parties"):
        for att in (party.get("attorneys") or []) if isinstance(party, dict) else []:
            if isinstance(att, dict) and att.get("name"):
                numbers[_norm(att["name"])] = att.get("attorneyNumber", "") or ""
    return numbers


def _enrich_attorney_numbers(
    parties: tuple[Party, ...], meta: dict
) -> tuple[Party, ...]:
    numbers = _attorney_numbers(meta)
    if not numbers:
        return parties
    return tuple(
        replace(
            party,
            attorneys=tuple(
                replace(att, number=numbers.get(_norm(att.name), att.number))
                for att in party.attorneys
            ),
        )
        for party in parties
    )


def _parse_docket(meta: dict, documents: tuple[DocumentRef, ...]) -> tuple[DocketEntry, ...]:
    """The re:SearchTX events table as docket entries, linking each named
    document back to a source PDF (by normalized filename, prefix-tolerant)."""
    by_key = {_norm(Path(d.filename).stem): d.intake_path for d in documents}

    def link(name: str) -> str:
        key = _norm(Path(name).stem)
        if key in by_key:
            return by_key[key]
        for other, path in by_key.items():
            if key[:24] == other[:24] or key.startswith(other[:22]) or other.startswith(key[:22]):
                return path
        return ""

    entries: list[DocketEntry] = []
    for row in _meta_table_rows(meta, "events"):
        if not isinstance(row, dict):
            continue
        docs = tuple(
            DocketDocument(
                name=dd.get("name", ""),
                declared_page_count=dd.get("pages") if isinstance(dd.get("pages"), int) else None,
                intake_path=link(dd.get("name", "")),
            )
            for dd in (row.get("documents") or [])
            if isinstance(dd, dict)
        )
        entries.append(
            DocketEntry(
                date=row.get("date", ""),
                event=row.get("event", ""),
                type=row.get("type", ""),
                comment=row.get("comments", "") or "",
                documents=docs,
            )
        )
    return tuple(entries)


def parse_combo(intake_dir: str | Path) -> CaseModel:
    """Parse a reconciled ``combo`` intake: the Odyssey export merged with the
    re:SearchTX ``meta.json`` so the model carries the best of both portals.

    Odyssey is the base (identity, parties, the phase-tagged event timeline,
    and the file-linked document set). From ody we also lift ``financials``.
    From re:SearchTX we merge attorney bar numbers onto parties, the
    ``hearings`` table (with results), and the richer ``docket`` (the judge's
    comments + per-document page counts), linking docket document names back to
    the source PDFs. With no meta.json present this degrades to parse_odyssey
    plus financials.
    """
    intake_dir = Path(intake_dir)
    base = parse_odyssey(intake_dir)
    meta = _load_json(intake_dir / RESEARCH_META_FILENAME)
    history = _load_json(intake_dir / CASE_HISTORY_FILENAME)
    register = _load_json(intake_dir / REGISTER_OF_ACTIONS_FILENAME)

    return replace(
        base,
        parties=_enrich_attorney_numbers(base.parties, meta),
        hearings=_parse_hearings(meta),
        financials=_parse_financials(history) or _parse_financials(register),
        docket=_parse_docket(meta, base.documents),
    )


# Provider folder name -> adapter. Aliases keep the selector forgiving.
# ``combo`` is the reconciled best-of-both intake (the recommended source of
# truth): the Odyssey export plus the re:SearchTX meta.json, merged by
# parse_combo so the model uses the best data from both portals.
PROVIDERS = {
    "ody": parse_odyssey,
    "odyssey": parse_odyssey,
    "combo": parse_combo,
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
