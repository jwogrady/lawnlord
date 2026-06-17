"""Tests for the canonical case standard (case.json) — round-trip + shape."""

import lawnlord as main
from lawnlord.providers import parse_combo


def test_to_canonical_shape(combo_intake):
    doc = main.to_canonical(parse_combo(combo_intake))
    assert doc["schemaVersion"] == main.CANONICAL_SCHEMA_VERSION
    assert doc["provider"] == "combo"
    assert doc["case"]["caseNumber"] == "99-00-12345"
    # merged sections from both portals are all present in one document
    assert doc["financials"]["balanceDue"] == "0"
    assert doc["hearings"][0]["result"] == "Canceled - Case Disposed"
    plaintiff = next(p for p in doc["parties"] if p["role"] == "Plaintiff")
    assert plaintiff["attorneys"][0]["number"] == "24000001"
    granted = next(d for d in doc["docket"] if "granted" in d["comment"])
    assert granted["documents"][0]["file"] == "filings/Final_Judgment.pdf"
    assert {d["file"] for d in doc["documents"]} >= {
        "filings/Final_Judgment.pdf",
        "filings/Petition.pdf",
    }


def test_canonical_round_trips_losslessly(combo_intake):
    model = parse_combo(combo_intake)
    assert main.from_canonical(main.to_canonical(model)) == model


def test_from_canonical_tolerates_minimal(tmp_path):
    # A minimal canonical doc (only a case number) loads without error.
    model = main.from_canonical({"provider": "combo", "case": {"caseNumber": "1-2-3"}})
    assert model.identity.case_number == "1-2-3"
    assert model.parties == ()
    assert model.financials is None
    assert model.docket == ()
