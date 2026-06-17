"""Test bootstrap.

The package lives under src/ (src/lawnlord/), so tests import it as
``import lawnlord`` (aliased to ``main`` in the test modules). pytest is
configured with ``pythonpath = ["src"]`` in pyproject.toml; this conftest adds
the same entry as a belt-and-braces fallback so the suite runs even when the
package is not installed and pytest is invoked from an unexpected cwd.
"""

import json
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# A hermetic Odyssey-shaped intake folder used by the workspace/provider tests.
# Mirrors the real four-JSON schema in miniature, with deliberate redundancy:
# the case header is richer in case-history than case-summary (to test the
# combine/precedence), and one document is listed under two docket rows (to
# test deduplication). No real case data is committed.
_CASE_SUMMARY = {
    "caseNumber": "99-00-12345",
    "caseTitle": "ACME ASSOCIATION VS. JOHN DOE",
    "dateFiled": "01/02/2025",
    "location": "1st Judicial District Court",
    "caseType": "Foreclosure - Other Foreclosure",
    "status": "Disposed",
    "sourceUrl": "https://example.test/CaseDetail",
}

_CASE_HISTORY = {
    "caseNumber": "99-00-12345",
    "caseTitle": "Acme Association v. John Doe",
    "caseType": "Foreclosure - Other Foreclosure",
    "court": "1st Judicial District Court, Test County, TX",
    "judicialOfficer": "Justice, Jane",
    "dateFiled": "2025-01-02",
    "status": "Disposed",
    "sourceUrl": "https://example.test/CaseDetail",
    "parties": [
        {
            "role": "Plaintiff",
            "name": "Acme Association",
            "attorneys": [
                {"name": "Pat Counsel", "status": "Retained", "phone": "555-0100"}
            ],
        },
        {
            "role": "Defendant",
            "name": "Doe, John",
            "representation": "Pro Se",
            "location": "Test City, TX",
        },
    ],
    "disposition": {
        "date": "2025-06-01",
        "type": "Summary Judgment",
        "files": ["filings/Final_Judgment.pdf"],
    },
    "timeline": [
        {
            "date": "2025-01-02",
            "phase": "Pleadings & Service",
            "event": "Original Petition",
            "description": "Suit commenced.",
            "files": ["filings/Petition.pdf"],
        },
        {
            "date": "2025-03-10",
            "phase": "Summary Judgment",
            "event": "Motion for Summary Judgment",
            "files": ["filings/Motion.pdf"],
        },
        {
            "date": "2025-06-01",
            "phase": "Judgment & Disposition",
            "event": "Final Judgment",
            "files": ["filings/Final_Judgment.pdf"],
        },
    ],
}

_REGISTER_OF_ACTIONS = {
    "caseNumber": "99-00-12345",
    "parties": [
        {"role": "Defendant", "name": "Doe, John", "representation": "Pro Se"},
        {"role": "Plaintiff", "name": "Acme Association"},
    ],
    "otherEventsAndHearings": [
        {"date": "01/02/2025", "description": "Original Petition (OCA)",
         "files": ["filings/Petition.pdf"]},
    ],
}

_FILINGS = {
    "caseNumber": "99-00-12345",
    "selectedEvent": [
        {"date": "06/01/2025", "event": "Summary Judgment",
         "image": "Final Judgment", "pageCount": 4,
         "file": "filings/Final_Judgment.pdf"},
    ],
    "otherEventsOnThisCase": [
        {"date": "01/02/2025", "event": "E-Filed Original Petition Document",
         "image": "Plaintiff's Original Petition", "pageCount": 6,
         "file": "filings/Petition.pdf"},
        {"date": "03/10/2025", "event": "Motion for Summary Judgment",
         "image": "Motion for Summary Judgment", "pageCount": 12,
         "file": "filings/Motion.pdf"},
        # Final_Judgment.pdf again under a second docket row — must dedupe.
        {"date": "06/01/2025", "event": "Summary Judgment",
         "image": "Final Judgment", "pageCount": 4,
         "file": "filings/Final_Judgment.pdf"},
    ],
    "otherImagesOnThisCase": [
        {"date": "01/05/2025", "event": "PDF Documents",
         "image": "Citation", "pageCount": 2,
         "file": "filings/Citation.pdf"},
    ],
}


@pytest.fixture
def ody_intake(tmp_path):
    """Create a hermetic Odyssey-shaped intake folder, returning its path.

    Folder is named ``ody`` so the provider selector resolves the Odyssey
    adapter. Holds the four metadata JSON files and an (empty) ``filings/`` dir.
    """
    intake = tmp_path / "ody"
    filings = intake / "filings"
    filings.mkdir(parents=True)
    for name, payload in (
        ("case-summary.json", _CASE_SUMMARY),
        ("case-history.json", _CASE_HISTORY),
        ("register-of-actions.json", _REGISTER_OF_ACTIONS),
        ("filings.json", _FILINGS),
    ):
        (intake / name).write_text(json.dumps(payload), encoding="utf-8")
    # Dummy source PDFs (distinct bytes -> distinct sha256) for the files the
    # docket references, so the ingest step can hash them into document IDs.
    for pdf in ("Final_Judgment.pdf", "Petition.pdf", "Motion.pdf", "Citation.pdf"):
        (filings / pdf).write_bytes(f"%PDF-1.4 {pdf}".encode("utf-8"))
    return intake
