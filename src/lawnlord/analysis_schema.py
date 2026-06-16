"""Page-analysis schema and the shared JSON writer.

legal_analysis_placeholders() defines the empty legal-review fields written
into every page stub — never pre-filled, since legal conclusions are human
work. write_json() is the one indented-JSON writer used across the build.
"""

from __future__ import annotations

import json
from pathlib import Path


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def legal_analysis_placeholders() -> dict:
    """Empty legal-review fields, one set per page. Never pre-filled: legal
    conclusions are human work, and anything tentative must be flagged for
    review rather than guessed."""
    return {
        "legalSummary": "",
        "keyFacts": [],
        "dates": [],
        "deadlines": [],
        "people": [],
        "organizations": [],
        "parties": [],
        "attorneys": [],
        "judges": [],
        "caseNumbers": [],
        "statutesOrRulesCited": [],
        "casesCited": [],
        "exhibitsReferenced": [],
        "claims": [],
        "defenses": [],
        "arguments": [],
        "reliefRequested": [],
        "ordersOrRulings": [],
        "timelineEvents": [],
        "tags": [],
        "notes": "",
    }
