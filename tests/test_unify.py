"""Unify the mirror views into the standard schema: ISO dates, gaps, and
per-field source provenance (docs/standard-schema.md)."""

from dataclasses import replace

import lawnlord as main
from lawnlord.providers import parse_combo


def test_normalize_date_forms():
    assert main.normalize_date("09/05/2025") == "2025-09-05"
    assert main.normalize_date("9/5/2025") == "2025-09-05"
    assert main.normalize_date("2025-09-05") == "2025-09-05"  # already ISO
    assert main.normalize_date("6/3/26, 4:59 AM") == "2026-06-03, 4:59 AM"  # 2-digit yr + time
    assert main.normalize_date("6/15/2026 09:00 AM") == "2026-06-15 09:00 AM"
    assert main.normalize_date("") == ""
    assert main.normalize_date("not a date") == "not a date"


def test_unify_normalizes_every_date(combo_intake):
    model = main.unify(parse_combo(combo_intake))
    iso = lambda s: (not s) or s[:4].isdigit() and s[4:5] == "-"
    assert iso(model.identity.date_filed)
    assert iso(model.identity.disposition_date)
    assert all(iso(e.date) for e in model.events)
    assert all(iso(h.date_time) for h in model.hearings)
    assert all(iso(d.date) for d in model.docket)
    assert all(iso(d.filing_date) for d in model.documents if d.filing_date)
    if model.financials:
        assert iso(model.financials.balance_as_of)
        assert all(iso(t.date) for t in model.financials.transactions)


def test_unify_is_idempotent(combo_intake):
    once = main.unify(parse_combo(combo_intake))
    assert main.unify(once) == once


def test_find_gaps_flags_missing_then_none(combo_intake):
    # The complete hermetic case has no gaps.
    assert main.find_gaps(parse_combo(combo_intake)) == []
    # A bare model is missing the standard fields.
    bare = main.CaseModel(provider="combo", identity=main.CaseIdentity(case_number="1-2-3"))
    gaps = main.find_gaps(bare)
    assert {"court", "caseType", "status", "parties", "documents", "financials"} <= set(gaps)


def test_source_provenance_maps_fields_to_views(combo_intake):
    prov = main.source_provenance(parse_combo(combo_intake))
    assert prov["caseNumber"] == ["ody", "txe"]  # both views have it
    assert prov["caseTypeAlt"] == ["txe"]  # re:SearchTX taxonomy
    assert prov["citationNumber"] == ["ody"]
    assert prov["hearings"] == ["txe"]
    assert prov["transactions"] == ["ody"]


def test_present_sources_degrades_without_txe(ody_intake, combo_intake):
    assert main.present_sources(parse_combo(combo_intake)) == ["ody", "txe"]
    assert main.present_sources(parse_combo(ody_intake)) == ["ody"]  # no meta.json


def test_canonical_v2_carries_standard_metadata(combo_intake):
    doc = main.to_canonical(main.unify(parse_combo(combo_intake)))
    assert doc["schemaVersion"] == "2.0"
    assert doc["sources"] == ["ody", "txe"]
    assert doc["gaps"] == []
    assert doc["provenance"]["caseTypeAlt"] == ["txe"]
    assert doc["case"]["dateFiled"] == "2025-01-02"  # ISO in the packed standard


def test_v2_round_trips_losslessly(combo_intake):
    # Derived gaps/sources/provenance don't break the model round-trip.
    model = main.unify(parse_combo(combo_intake))
    assert main.from_canonical(main.to_canonical(model)) == model
