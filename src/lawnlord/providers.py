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
    aliases: tuple[str, ...] = ()  # re:SearchTX nicknameAlias values


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
class FinancialTransaction:
    """One line of the Odyssey financial ledger (register-of-actions)."""

    date: str = ""
    description: str = ""
    amount: str = ""


@dataclass(frozen=True)
class Financials:
    """Money assessed/paid on the case (from the Odyssey financial summary),
    with the per-line ``transactions`` ledger when the register provides it."""

    party: str = ""
    total_assessment: str = ""
    total_payments: str = ""
    balance_due: str = ""
    balance_as_of: str = ""
    transactions: tuple[FinancialTransaction, ...] = ()


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
    """The case header, combined from case-summary + case-history (and, for a
    combo intake, the re:SearchTX view: case_category / clerk / last_refreshed)."""

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
    # Field-complete capture (docs/standard-schema.md): nothing the sources
    # expose is dropped before unification.
    citation_number: str = ""  # ody case-summary citationNumber
    disposition_comment: str = ""  # ody disposition comment
    disposition_judicial_officer: str = ""  # ody disposition judicialOfficer
    case_category: str = ""  # re:SearchTX caseCategory (the other taxonomy)
    clerk: str = ""  # re:SearchTX location (the clerk/venue facet)
    last_refreshed: str = ""  # re:SearchTX caseLastRefreshed (freshness)


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
    # Field-complete capture of the remaining source structures (combo intake).
    case_flags: tuple[str, ...] = ()  # re:SearchTX caseFlags rows
    case_cross_references: tuple[str, ...] = ()  # re:SearchTX caseCrossReferences rows
    source_note: str = ""  # re:SearchTX _meta.extractedNote (a completeness caveat)


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


def _parse_transactions(fi: dict) -> tuple[FinancialTransaction, ...]:
    """The per-line financial ledger from a financialInformation block."""
    def s(value) -> str:
        return "" if value is None else str(value)

    return tuple(
        FinancialTransaction(
            date=t.get("date", ""),
            description=t.get("description", ""),
            amount=s(t.get("amount")),
        )
        for t in (fi.get("transactions") or [])
        if isinstance(t, dict)
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
        citation_number=summary.get("citationNumber") or "",
        disposition_comment=disposition.get("comment", ""),
        disposition_judicial_officer=disposition.get("judicialOfficer", ""),
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
        transactions=_parse_transactions(fi),
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


def _meta_case_info(meta: dict) -> dict:
    ci = meta.get("caseInformation")
    return ci if isinstance(ci, dict) else {}


def _enrich_identity(identity: CaseIdentity, meta: dict) -> CaseIdentity:
    """Merge the re:SearchTX view's distinct facets onto the identity: its own
    category taxonomy, the clerk/venue, and the refresh timestamp."""
    ci = _meta_case_info(meta)
    if not ci:
        return identity
    return replace(
        identity,
        case_category=ci.get("caseCategory", "") or identity.case_category,
        clerk=ci.get("location", "") or identity.clerk,
        last_refreshed=ci.get("caseLastRefreshed", "") or identity.last_refreshed,
    )


def _enrich_aliases(parties: tuple[Party, ...], meta: dict) -> tuple[Party, ...]:
    """Attach re:SearchTX nicknameAlias values to the matching party by name."""
    aliases: dict[str, str] = {}
    for p in _meta_table_rows(meta, "parties"):
        if isinstance(p, dict) and p.get("name"):
            alias = p.get("nicknameAlias")
            if alias and alias != "None":
                aliases[_norm(p["name"])] = alias
    if not aliases:
        return parties
    return tuple(
        replace(p, aliases=(aliases[_norm(p.name)],))
        if _norm(p.name) in aliases
        else p
        for p in parties
    )


def _meta_rows_json(meta: dict, key: str) -> tuple[str, ...]:
    """Capture a meta table's rows verbatim (as JSON) so nothing is dropped,
    even for sections we do not yet model structurally (flags, cross-refs)."""
    return tuple(
        json.dumps(r, sort_keys=True)
        for r in _meta_table_rows(meta, key)
        if isinstance(r, dict) and r
    )


def _combo_financials(history: dict, register: dict) -> Financials | None:
    """The financial summary (case-history), enriched with the per-line ledger
    from register-of-actions when the summary block omits it."""
    fin = _parse_financials(history) or _parse_financials(register)
    if fin is None:
        return None
    if not fin.transactions:
        reg = _parse_financials(register)
        if reg and reg.transactions:
            fin = replace(fin, transactions=reg.transactions)
    return fin


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
    note = (meta.get("_meta") or {}).get("extractedNote", "") if isinstance(meta, dict) else ""

    parties = _enrich_aliases(_enrich_attorney_numbers(base.parties, meta), meta)
    return replace(
        base,
        identity=_enrich_identity(base.identity, meta),
        parties=parties,
        hearings=_parse_hearings(meta),
        financials=_combo_financials(history, register),
        docket=_parse_docket(meta, base.documents),
        case_flags=_meta_rows_json(meta, "caseFlags"),
        case_cross_references=_meta_rows_json(meta, "caseCrossReferences"),
        source_note=note,
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
