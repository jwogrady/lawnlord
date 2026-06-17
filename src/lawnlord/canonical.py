"""The canonical case standard: lawnlord's portable, versioned representation
of a case, serialized as ``case.json``.

Provider adapters (:mod:`lawnlord.providers`) populate the in-memory
``CaseModel`` from whatever raw source exports exist (Odyssey, re:SearchTX, a
reconciled ``combo``). This module is the single definition of how that model
serializes to — and loads back from — the canonical JSON, so a packed case is
self-describing and round-trips losslessly:

    to_canonical(model)  ->  dict   (case.json)
    from_canonical(dict) ->  CaseModel

``case.json`` is "all the data"; the packed source-of-truth zip pairs it with
``files/`` (all the PDFs). Bump SCHEMA_VERSION on any incompatible field change.
"""

from __future__ import annotations

from .providers import (
    Attorney,
    CaseIdentity,
    CaseModel,
    DocketDocument,
    DocketEntry,
    DocumentRef,
    Event,
    Financials,
    Hearing,
    Party,
)

SCHEMA_VERSION = "1.0"


def _identity(identity: CaseIdentity) -> dict:
    return {
        "caseNumber": identity.case_number,
        "title": identity.title,
        "court": identity.court,
        "judicialOfficer": identity.judicial_officer,
        "caseType": identity.case_type,
        "status": identity.status,
        "dateFiled": identity.date_filed,
        "disposition": {
            "type": identity.disposition_type,
            "date": identity.disposition_date,
        },
        "sourceUrl": identity.source_url,
    }


def _party(party: Party) -> dict:
    return {
        "role": party.role,
        "name": party.name,
        "representation": party.representation,
        "location": party.location,
        "attorneys": [
            {"name": a.name, "number": a.number, "status": a.status, "phone": a.phone}
            for a in party.attorneys
        ],
    }


def _financials(fin: Financials | None) -> dict | None:
    if fin is None:
        return None
    return {
        "party": fin.party,
        "assessment": fin.total_assessment,
        "payments": fin.total_payments,
        "balanceDue": fin.balance_due,
        "asOf": fin.balance_as_of,
    }


def _hearing(h: Hearing) -> dict:
    return {
        "dateTime": h.date_time,
        "type": h.hearing_type,
        "judge": h.judge,
        "location": h.location,
        "result": h.result,
    }


def _event(e: Event) -> dict:
    return {
        "date": e.date,
        "phase": e.phase,
        "event": e.event,
        "description": e.description,
        "party": e.party,
        "files": list(e.files),
    }


def _docket_entry(d: DocketEntry) -> dict:
    return {
        "date": d.date,
        "event": d.event,
        "type": d.type,
        "comment": d.comment,
        "documents": [
            {"name": dd.name, "pages": dd.declared_page_count, "file": dd.intake_path}
            for dd in d.documents
        ],
    }


def _document(doc: DocumentRef) -> dict:
    return {
        "file": doc.intake_path,
        "filename": doc.filename,
        "title": doc.title,
        "declaredPageCount": doc.declared_page_count,
        "docketEvent": doc.docket_event,
        "filingDate": doc.filing_date,
    }


def to_canonical(model: CaseModel) -> dict:
    """Serialize a CaseModel to the canonical case.json structure."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provider": model.provider,
        "case": _identity(model.identity),
        "parties": [_party(p) for p in model.parties],
        "financials": _financials(model.financials),
        "hearings": [_hearing(h) for h in model.hearings],
        "events": [_event(e) for e in model.events],
        "docket": [_docket_entry(d) for d in model.docket],
        "documents": [_document(d) for d in model.documents],
    }


# --- load back -------------------------------------------------------------


def _read_identity(case: dict) -> CaseIdentity:
    disposition = case.get("disposition") or {}
    return CaseIdentity(
        case_number=case.get("caseNumber", ""),
        title=case.get("title", ""),
        court=case.get("court", ""),
        judicial_officer=case.get("judicialOfficer", ""),
        case_type=case.get("caseType", ""),
        status=case.get("status", ""),
        date_filed=case.get("dateFiled", ""),
        disposition_type=disposition.get("type", ""),
        disposition_date=disposition.get("date", ""),
        source_url=case.get("sourceUrl", ""),
    )


def _read_party(p: dict) -> Party:
    return Party(
        role=p.get("role", ""),
        name=p.get("name", ""),
        representation=p.get("representation", ""),
        location=p.get("location", ""),
        attorneys=tuple(
            Attorney(
                name=a.get("name", ""),
                status=a.get("status", ""),
                phone=a.get("phone", ""),
                number=a.get("number", ""),
            )
            for a in (p.get("attorneys") or [])
        ),
    )


def from_canonical(data: dict) -> CaseModel:
    """Rebuild a CaseModel from a canonical case.json structure (the inverse of
    to_canonical for all fields this standard defines)."""
    fin = data.get("financials")
    financials = (
        Financials(
            party=fin.get("party", ""),
            total_assessment=fin.get("assessment", ""),
            total_payments=fin.get("payments", ""),
            balance_due=fin.get("balanceDue", ""),
            balance_as_of=fin.get("asOf", ""),
        )
        if isinstance(fin, dict)
        else None
    )
    return CaseModel(
        provider=data.get("provider", ""),
        identity=_read_identity(data.get("case") or {}),
        parties=tuple(_read_party(p) for p in (data.get("parties") or [])),
        events=tuple(
            Event(
                date=e.get("date", ""),
                phase=e.get("phase", ""),
                event=e.get("event", ""),
                description=e.get("description", ""),
                party=e.get("party", ""),
                files=tuple(e.get("files") or []),
            )
            for e in (data.get("events") or [])
        ),
        documents=tuple(
            DocumentRef(
                intake_path=d.get("file", ""),
                filename=d.get("filename", ""),
                title=d.get("title", ""),
                declared_page_count=d.get("declaredPageCount"),
                docket_event=d.get("docketEvent", ""),
                filing_date=d.get("filingDate", ""),
            )
            for d in (data.get("documents") or [])
        ),
        hearings=tuple(
            Hearing(
                date_time=h.get("dateTime", ""),
                hearing_type=h.get("type", ""),
                judge=h.get("judge", ""),
                location=h.get("location", ""),
                result=h.get("result", ""),
            )
            for h in (data.get("hearings") or [])
        ),
        financials=financials,
        docket=tuple(
            DocketEntry(
                date=d.get("date", ""),
                event=d.get("event", ""),
                type=d.get("type", ""),
                comment=d.get("comment", ""),
                documents=tuple(
                    DocketDocument(
                        name=dd.get("name", ""),
                        declared_page_count=dd.get("pages"),
                        intake_path=dd.get("file", ""),
                    )
                    for dd in (d.get("documents") or [])
                ),
            )
            for d in (data.get("docket") or [])
        ),
    )
