"""Package a case as the shippable source of truth.

A packed case is one self-contained zip:

    case.json        the canonical standard — all the data
    filings/<pdf>    all the source PDFs — all the files

The file paths in ``case.json`` (each document's ``file``) are the same
relative paths the PDFs sit at inside the zip, so the artifact is internally
consistent and can be read back without any portal access.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from .canonical import to_canonical
from .unify import unify
from .workspace import Case

CASE_JSON_NAME = "case.json"


def pack_case(case: Case, out_zip: str | Path) -> dict:
    """Write ``case.json`` + every resolvable source PDF into ``out_zip``.

    Files are stored at their canonical ``file`` path (e.g. ``filings/Foo.pdf``)
    so the zip matches what ``case.json`` references. Returns stats including
    any documents whose source PDF was missing on disk.
    """
    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    # Pack the standard (normalized) view: ISO dates, source provenance, gaps.
    canonical = to_canonical(unify(case.model))

    packed: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(CASE_JSON_NAME, json.dumps(canonical, indent=2))
        for doc in case.model.documents:
            rel = doc.intake_path
            if not rel or rel in seen:
                continue
            seen.add(rel)
            source = case.intake_dir / rel
            if not source.exists():
                missing.append(rel)
                continue
            z.write(source, rel)
            packed.append(rel)

    return {
        "out_zip": str(out_zip),
        "provider": case.model.provider,
        "documents": len(case.model.documents),
        "packed": len(packed),
        "missing": missing,
    }
