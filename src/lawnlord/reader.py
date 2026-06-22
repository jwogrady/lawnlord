"""Read a deterministic ``rake`` intake zip into a :class:`~lawnlord.models.CaseModel`.

The intake zip is the single source of truth: ``data.json`` (the case record,
described by the bundled ``schema.json``), ``manifest.json`` (capture metadata +
per-file sha256), ``files/`` (the filed PDFs), and ``pages/`` (the captured portal
HTML). This module:

- extracts the zip **safely** (every entry checked with
  :func:`~lawnlord.models.is_suspicious_entry` — no path traversal),
- **validates** ``data.json`` against the zip's own ``schema.json`` (fail loud if
  the export drifts from its contract),
- maps ``data.json`` into a ``CaseModel`` — values kept **verbatim** (strings, as
  the zip types them); typing/normalization is a derived concern, never here.

It mints no IDs and guesses nothing; output is a pure function of the zip.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import jsonschema

from .models import (
    CaseIdentity,
    CaseModel,
    DocumentRef,
    Event,
    Financials,
    FinancialTransaction,
    Party,
    is_suspicious_entry,
)

DATA_FILENAME = "data.json"
SCHEMA_FILENAME = "schema.json"
MANIFEST_FILENAME = "manifest.json"

# Deterministic fallback when a zip carries no manifest capturedAt: a fixed
# sentinel (never wall-clock) so re-imports stay byte-identical.
_FALLBACK_GENERATED_AT = "1980-01-01T00:00:00Z"


def extract_zip(zip_path: str | Path, dest: str | Path) -> Path:
    """Extract a rake intake zip into ``dest`` safely, returning ``dest``.

    Every entry is checked with :func:`is_suspicious_entry`; a traversal or
    absolute path raises rather than writing outside ``dest``.
    """
    zip_path = Path(zip_path)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if is_suspicious_entry(name):
                raise ValueError(f"unsafe zip entry refused: {name!r}")
        zf.extractall(dest)
    return dest


def _load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"missing {path.name}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_data(intake_dir: str | Path) -> list:
    """Load ``data.json`` and validate it against the bundled ``schema.json``.

    Raises ``jsonschema.ValidationError`` if the data drifts from its own
    declared contract. Returns the parsed ``data.json`` (a list of case objects).
    """
    intake_dir = Path(intake_dir)
    data = _load_json(intake_dir / DATA_FILENAME)
    schema = _load_json(intake_dir / SCHEMA_FILENAME)
    jsonschema.validate(instance=data, schema=schema)
    return data


def captured_at(intake_dir: str | Path) -> str:
    """The zip's capture timestamp (``manifest.json`` ``capturedAt``) — used as a
    deterministic ``generated_at`` so re-imports are reproducible. Falls back to a
    fixed sentinel (never wall-clock) when no manifest is present."""
    path = Path(intake_dir) / MANIFEST_FILENAME
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(manifest, dict) and manifest.get("capturedAt"):
            return str(manifest["capturedAt"])
    return _FALLBACK_GENERATED_AT


def _split_representation(rep: list | None) -> tuple[str, str]:
    """A party's ``representation`` array → (representation, location).

    The first element is the representation note (``"Pro Se"`` or counsel); any
    remaining elements are the location/address, joined verbatim.
    """
    items = [str(x) for x in (rep or []) if x]
    if not items:
        return "", ""
    return items[0], "; ".join(items[1:])


def _parse_parties(raw: list | None) -> tuple[Party, ...]:
    out = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        representation, location = _split_representation(p.get("representation"))
        out.append(
            Party(
                role=p.get("role", ""),
                name=p.get("name", ""),
                representation=representation,
                location=location,
            )
        )
    return tuple(out)


def _page_count(value) -> int | None:
    """``"Page Count"`` is a string in the zip; coerce to int, or None."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_documents(raw: list | None) -> tuple[DocumentRef, ...]:
    """Filed PDFs from ``documents[]``, deduped by file path (first wins),
    sorted by intake path for deterministic output."""
    by_path: dict[str, DocumentRef] = {}
    for d in raw or []:
        if not isinstance(d, dict):
            continue
        path = d.get("file", "")
        if not path or path in by_path:
            continue
        by_path[path] = DocumentRef(
            intake_path=path,
            filename=Path(path).name,
            title=d.get("Image", ""),
            declared_page_count=_page_count(d.get("Page Count")),
            docket_event=d.get("event", ""),
            filing_date=d.get("date", ""),
        )
    return tuple(by_path[p] for p in sorted(by_path))


def _parse_events(raw: list | None) -> tuple[Event, ...]:
    """Docket events from ``registerOfActions[]``. ``section`` is the phase;
    each entry's ``documents`` (file paths) become the event's ``files``."""
    out = []
    for e in raw or []:
        if not isinstance(e, dict):
            continue
        out.append(
            Event(
                date=e.get("date", ""),
                phase=e.get("section", ""),
                event=e.get("event", ""),
                files=tuple(e.get("documents", []) or []),
            )
        )
    return tuple(out)


def _parse_financials(raw: dict | None) -> Financials | None:
    if not isinstance(raw, dict) or not raw:
        return None
    txns = tuple(
        FinancialTransaction(
            date=t.get("date", ""),
            description=t.get("description", ""),
            amount=str(t.get("amount", "")),
        )
        for t in (raw.get("transactions") or [])
        if isinstance(t, dict)
    )
    return Financials(
        party=raw.get("assessedTo", ""),
        total_assessment=str(raw.get("totalAssessment", "")),
        total_payments=str(raw.get("totalPayments", "")),
        balance_due=str(raw.get("balanceDue", "")),
        balance_as_of=str(raw.get("balanceAsOf", "")),
        transactions=txns,
    )


def _to_model(case: dict) -> CaseModel:
    identity = CaseIdentity(
        case_number=case.get("caseNumber", ""),
        case_type=case.get("caseType", ""),
        date_filed=case.get("dateFiled", ""),
        court=case.get("location", ""),
    )
    return CaseModel(
        provider="rake",
        identity=identity,
        parties=_parse_parties(case.get("parties")),
        events=_parse_events(case.get("registerOfActions")),
        documents=_parse_documents(case.get("documents")),
        financials=_parse_financials(case.get("financial")),
    )


def load_case_model(intake_dir: str | Path) -> CaseModel:
    """Read + validate ``data.json`` in ``intake_dir`` and map it to a
    ``CaseModel``. ``intake_dir`` is an extracted intake zip (it must contain
    ``data.json`` and ``schema.json``; ``files/`` holds the filed PDFs)."""
    data = validate_data(intake_dir)
    if not isinstance(data, list) or not data:
        raise ValueError(f"data.json in {intake_dir} has no case records")
    if len(data) != 1:
        # The rake export is one case per zip (manifest records: 1). More than
        # one would silently lose cases 2..N — fail loud instead of taking [0].
        raise ValueError(
            f"data.json in {intake_dir} has {len(data)} case records; expected exactly 1"
        )
    return _to_model(data[0])
