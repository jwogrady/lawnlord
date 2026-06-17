"""Compile the two portal views into one complete intake — `lawnlord combine`.

``ody`` (Odyssey) and ``txe`` (re:SearchTX) are two views of the same case and
are easy to re-download. **combo** is the act of compiling them into one provider
intake the rest of the tools read: Odyssey's case JSONs + ``filings/`` (the filed
PDFs), overlaid with re:SearchTX's ``meta.json``. This module *stages* that folder;
:func:`lawnlord.providers.parse_combo` then *merges* the two into one model at read
time (attorney bar numbers, hearings, financials, the richer docket).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ODY_JSONS = (
    "case-summary.json",
    "case-history.json",
    "filings.json",
    "register-of-actions.json",
)
META = "meta.json"


def combine(
    ody_dir: str | Path, txe_dir: str | Path | None, out_dir: str | Path
) -> dict:
    """Stage a combo intake at ``out_dir`` from the ``ody`` and ``txe`` views.

    Odyssey supplies the case JSONs and the filed PDFs (``filings/``);
    re:SearchTX supplies ``meta.json`` (the enrichment merged in at parse time).
    Returns a summary of what was compiled.
    """
    ody = Path(ody_dir).resolve()
    txe = Path(txe_dir).resolve() if txe_dir else None
    out = Path(out_dir).resolve()
    if not (ody / "filings").is_dir():
        raise FileNotFoundError(
            f"{ody} has no filings/ directory. The Odyssey (ody) view is the source of the "
            "case JSONs and the filed PDFs — extract its PDFs into filings/ first."
        )

    out.mkdir(parents=True, exist_ok=True)
    jsons = 0
    for name in ODY_JSONS:
        src = ody / name
        if src.exists():
            shutil.copy2(src, out / name)
            jsons += 1
    shutil.copytree(ody / "filings", out / "filings", dirs_exist_ok=True)
    filings = len(list((out / "filings").glob("*.pdf")))

    meta = False
    if txe and (txe / META).exists():
        shutil.copy2(txe / META, out / META)
        meta = True

    manifest = {
        "sources": {"ody": str(ody), "txe": str(txe) if txe else None},
        "odyJsons": jsons,
        "filings": filings,
        "meta": meta,
    }
    (out / "combo-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return {"out": str(out), "ody_jsons": jsons, "filings": filings, "meta": meta}
