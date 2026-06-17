"""Unify the mirror-view source models into the standard court schema.

``txe`` (re:SearchTX) and ``ody`` (Odyssey) are two *views of the same court
record*, so this is normalization + view-unification, not conflict resolution
(see ``docs/standard-schema.md``). This module:

- ``unify(model)`` — normalize the merged model into the standard: dates to ISO
  (the one genuinely divergent format across views). caseType keeps the more
  specific value with the other taxonomy as ``case_category``; the court and
  clerk facets are both kept — all already captured upstream, so unify's active
  job is date normalization. (Person/org name reformatting is deliberately *not*
  done: Odyssey already supplies the canonical ``Last, First`` person form, and
  blind reformatting would corrupt organization names.)
- ``find_gaps(model)`` — the standard fields a complete case should have that are
  missing, surfaced so the record's soft spots are explicit.
- ``source_provenance(model)`` / ``present_sources(model)`` — which view supplies
  each standard field, per the standard-schema source map.

Determinism: pure functions of the model; no I/O, no clock.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .providers import CaseModel

_MDY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})(.*)$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_date(value: str) -> str:
    """Normalize a US ``M/D/Y`` (or ``MM/DD/YYYY``) date to ISO ``YYYY-MM-DD``,
    preserving any trailing time. Already-ISO dates and unparseable strings are
    returned unchanged. Two-digit years map to 20xx."""
    s = (value or "").strip()
    if not s or _ISO.match(s):
        return s
    m = _MDY.match(s)
    if not m:
        return s
    mo, d, y, rest = m.groups()
    year = int(y)
    if year < 100:
        year += 2000
    try:
        iso = f"{year:04d}-{int(mo):02d}-{int(d):02d}"
    except ValueError:
        return s
    return f"{iso}{rest}" if rest.strip() else iso


def unify(model: CaseModel) -> CaseModel:
    """Return a normalized copy of the merged model: every date is ISO. Other
    standard normalizations (caseType+alt, court+clerk) are captured upstream;
    name reformatting is intentionally left to the source-canonical form."""
    nd = normalize_date
    identity = replace(
        model.identity,
        date_filed=nd(model.identity.date_filed),
        disposition_date=nd(model.identity.disposition_date),
        last_refreshed=nd(model.identity.last_refreshed),
    )
    events = tuple(replace(e, date=nd(e.date)) for e in model.events)
    hearings = tuple(replace(h, date_time=nd(h.date_time)) for h in model.hearings)
    docket = tuple(replace(d, date=nd(d.date)) for d in model.docket)
    documents = tuple(replace(d, filing_date=nd(d.filing_date)) for d in model.documents)
    financials = model.financials
    if financials is not None:
        financials = replace(
            financials,
            balance_as_of=nd(financials.balance_as_of),
            transactions=tuple(
                replace(t, date=nd(t.date)) for t in financials.transactions
            ),
        )
    return replace(
        model,
        identity=identity,
        events=events,
        hearings=hearings,
        docket=docket,
        documents=documents,
        financials=financials,
    )


# Standard field -> the view(s) that supply it (docs/standard-schema.md). For a
# mirror record the value is one normalized truth; this records its origin.
_BOTH = ("ody", "txe")
FIELD_SOURCES: dict[str, tuple[str, ...]] = {
    "caseNumber": _BOTH,
    "title": _BOTH,
    "dateFiled": _BOTH,
    "judicialOfficer": _BOTH,
    "status": ("ody",),
    "caseType": ("ody",),
    "court": ("ody",),
    "citationNumber": ("ody",),
    "disposition": ("ody",),
    "financials": ("ody",),
    "transactions": ("ody",),
    "events": ("ody",),
    "caseTypeAlt": ("txe",),
    "clerk": ("txe",),
    "lastRefreshed": ("txe",),
    "hearings": ("txe",),
    "docket": ("txe",),
    "attorneyBarNumbers": ("txe",),
    "aliases": ("txe",),
    "sourceNote": ("txe",),
}


def present_sources(model: CaseModel) -> list[str]:
    """The views that contributed to this model: always ``ody`` (the base); add
    ``txe`` when the re:SearchTX-only structures are present."""
    has_txe = bool(
        model.hearings
        or model.docket
        or model.identity.case_category
        or model.source_note
        or any(a.number for p in model.parties for a in p.attorneys)
    )
    return ["ody", "txe"] if has_txe else ["ody"]


def source_provenance(model: CaseModel) -> dict[str, list[str]]:
    """Map each *populated* standard field to the view(s) that supply it,
    filtered to the sources actually present in this model."""
    present = set(present_sources(model))
    ident = model.identity
    has: dict[str, bool] = {
        "caseNumber": bool(ident.case_number),
        "title": bool(ident.title),
        "dateFiled": bool(ident.date_filed),
        "judicialOfficer": bool(ident.judicial_officer),
        "status": bool(ident.status),
        "caseType": bool(ident.case_type),
        "court": bool(ident.court),
        "citationNumber": bool(ident.citation_number),
        "disposition": bool(ident.disposition_type),
        "financials": model.financials is not None,
        "transactions": bool(model.financials and model.financials.transactions),
        "events": bool(model.events),
        "caseTypeAlt": bool(ident.case_category),
        "clerk": bool(ident.clerk),
        "lastRefreshed": bool(ident.last_refreshed),
        "hearings": bool(model.hearings),
        "docket": bool(model.docket),
        "attorneyBarNumbers": any(a.number for p in model.parties for a in p.attorneys),
        "aliases": any(p.aliases for p in model.parties),
        "sourceNote": bool(model.source_note),
    }
    out: dict[str, list[str]] = {}
    for field, populated in has.items():
        if not populated:
            continue
        srcs = [s for s in FIELD_SOURCES.get(field, ()) if s in present]
        if srcs:
            out[field] = srcs
    return out


def find_gaps(model: CaseModel) -> list[str]:
    """Standard fields a complete case should carry that are missing here —
    surfaced (not hidden) so the record's soft spots are explicit."""
    ident = model.identity
    checks = {
        "court": bool(ident.court),
        "judicialOfficer": bool(ident.judicial_officer),
        "caseType": bool(ident.case_type),
        "status": bool(ident.status),
        "dateFiled": bool(ident.date_filed),
        "disposition": bool(ident.disposition_type),
        "financials": model.financials is not None,
        "parties": bool(model.parties),
        "documents": bool(model.documents),
    }
    return [field for field, present in checks.items() if not present]
