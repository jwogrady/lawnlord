"""Tests for `lawnlord pack` — the shippable source-of-truth zip."""

import json
import zipfile

import lawnlord as main
from lawnlord.workspace import Case


def test_pack_produces_case_json_and_files(combo_intake, tmp_path):
    case = Case.from_intake(combo_intake)
    out = tmp_path / "case.zip"
    stats = main.pack_case(case, out)

    assert out.exists()
    assert stats["packed"] == 4  # the four deduped documents in the fixture
    assert stats["missing"] == []

    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert "case.json" in names
        # Files are stored at their canonical `file` path, so they match case.json.
        assert "filings/Final_Judgment.pdf" in names
        assert "filings/Petition.pdf" in names
        canonical = json.loads(z.read("case.json"))

    # The packed case.json is itself a valid canonical doc that round-trips.
    assert canonical["schemaVersion"] == main.CANONICAL_SCHEMA_VERSION
    model = main.from_canonical(canonical)
    assert model.identity.case_number == "99-00-12345"
    assert model == case.model
    # Every document's `file` resolves to a real entry inside the zip.
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
    for doc in model.documents:
        assert doc.intake_path in names


def test_pack_reports_missing_source_pdf(combo_intake, tmp_path):
    # Remove one source PDF; pack should still succeed and report it missing.
    (combo_intake / "filings" / "Petition.pdf").unlink()
    case = Case.from_intake(combo_intake)
    stats = main.pack_case(case, tmp_path / "case.zip")
    assert "filings/Petition.pdf" in stats["missing"]
    assert stats["packed"] == 3
