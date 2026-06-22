"""Characterization tests for the zip → CaseModel → DuckDB import (F1, #92).

Hermetic: every test builds a tiny intake folder in tmp_path (data.json +
schema.json + manifest.json + files/), never real case data.
"""

import json
import zipfile

import jsonschema
import pytest

import lawnlord as main

_GOOD_CASE = {
    "caseNumber": "99-00-12345",
    "caseType": "Foreclosure - Other",
    "dateFiled": "01/02/2025",
    "location": "284th Judicial District Court",
    "parties": [
        {"name": "Doe, John", "role": "Defendant", "representation": ["Pro Se", "Town, TX"]},
        {"name": "ACME HOA", "role": "Plaintiff", "representation": ["Jane Lawyer Retained"]},
    ],
    "documents": [
        {
            "Image": "Plaintiff's Original Petition",
            "Page Count": "6",
            "date": "01/02/2025",
            "event": "E-Filed Original Petition",
            "file": "files/doc-1.pdf",
            "events": [{"date": "01/02/2025", "event": "E-Filed Original Petition"}],
        }
    ],
    "registerOfActions": [
        {"date": "01/02/2025", "event": "Original Petition (OCA)", "section": "other events and hearings"},
        {
            "date": "01/02/2025",
            "event": "E-Filed Original Petition",
            "section": "other events and hearings",
            "documents": ["files/doc-1.pdf"],
        },
    ],
    "financial": {
        "assessedTo": "Plaintiff ACME HOA",
        "balanceAsOf": "06/20/2026",
        "balanceDue": "0.00",
        "totalAssessment": "366.00",
        "totalPayments": "366.00",
        "transactions": [
            {"amount": "366.00", "date": "01/03/2025", "description": "Transaction Assessment"}
        ],
    },
}

_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "caseNumber": {"type": "string"},
            "caseType": {"type": "string"},
            "dateFiled": {"type": "string"},
            "location": {"type": "string"},
            "parties": {"type": "array"},
            "documents": {"type": "array"},
            "registerOfActions": {"type": "array"},
            "financial": {"type": "object"},
        },
        "required": ["caseNumber"],
    },
}

_MANIFEST = {"capturedAt": "2026-06-20T16:42:56Z"}


def _make_intake(tmp_path, case=None):
    """Build an extracted-intake dir: data.json + schema.json + manifest + files/."""
    d = tmp_path / "intake"
    (d / "files").mkdir(parents=True)
    (d / "data.json").write_text(json.dumps([case or _GOOD_CASE]), encoding="utf-8")
    (d / "schema.json").write_text(json.dumps(_SCHEMA), encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps(_MANIFEST), encoding="utf-8")
    (d / "files" / "doc-1.pdf").write_bytes(b"%PDF-1.4\n%fake petition bytes\n%%EOF")
    return d


def _counts(case_dir):
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        return {
            t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("cases", "parties", "events", "images", "image_events",
                      "financials", "financial_transactions")
        }
    finally:
        con.close()


# --- mapping --------------------------------------------------------------


def test_load_case_model_maps_data(tmp_path):
    model = main.load_case_model(_make_intake(tmp_path))
    assert model.provider == "rake"
    assert model.identity.case_number == "99-00-12345"
    assert model.identity.case_type == "Foreclosure - Other"
    assert model.identity.court == "284th Judicial District Court"
    assert len(model.parties) == 2
    # representation array → (representation, location)
    defendant = next(p for p in model.parties if p.role == "Defendant")
    assert defendant.representation == "Pro Se"
    assert defendant.location == "Town, TX"
    assert len(model.documents) == 1
    doc = model.documents[0]
    assert doc.intake_path == "files/doc-1.pdf"
    assert doc.filename == "doc-1.pdf"
    assert doc.declared_page_count == 6  # "6" string → int
    assert len(model.events) == 2
    assert model.events[1].files == ("files/doc-1.pdf",)
    assert model.financials is not None
    assert model.financials.total_assessment == "366.00"  # verbatim string
    assert len(model.financials.transactions) == 1


# --- DuckDB import --------------------------------------------------------


def test_import_populates_duckdb(tmp_path):
    intake = _make_intake(tmp_path)
    case_dir = tmp_path / "out"
    main.main(["import", str(intake), "--case-dir", str(case_dir)])
    assert _counts(case_dir) == {
        "cases": 1, "parties": 2, "events": 2, "images": 1,
        "image_events": 1, "financials": 1, "financial_transactions": 1,
    }


def test_schema_has_the_seven_mirror_tables(tmp_path):
    con = main.open_case_db(tmp_path / "lawnlord.duckdb")
    main.apply_schema(con)
    tables = {
        r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    con.close()
    # The mirror is always present; the Exploded layer (documents, pages) is
    # additive on top (F3), so the mirror is a subset, not the whole set.
    assert {
        "schema_meta", "cases", "parties", "events", "images",
        "image_events", "financials", "financial_transactions",
    } <= tables


# --- validation -----------------------------------------------------------


def test_validation_rejects_data_that_drifts_from_schema(tmp_path):
    bad = dict(_GOOD_CASE)
    bad["caseNumber"] = 12345  # schema requires a string
    intake = _make_intake(tmp_path, case=bad)
    with pytest.raises(jsonschema.ValidationError):
        main.load_case_model(intake)


def test_load_case_model_rejects_multiple_cases(tmp_path):
    # The rake zip is one case per export; >1 must fail loud, not silently drop.
    d = tmp_path / "intake"
    (d / "files").mkdir(parents=True)
    (d / "data.json").write_text(json.dumps([_GOOD_CASE, _GOOD_CASE]), encoding="utf-8")
    (d / "schema.json").write_text(json.dumps(_SCHEMA), encoding="utf-8")
    with pytest.raises(ValueError, match="expected exactly 1"):
        main.load_case_model(d)


# --- safety ---------------------------------------------------------------


def test_extract_zip_refuses_path_traversal(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escape.txt", "nope")
    with pytest.raises(ValueError):
        main.extract_zip(z, tmp_path / "dest")


def test_extract_zip_roundtrips_a_real_zip(tmp_path):
    intake = _make_intake(tmp_path)
    z = tmp_path / "case.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in intake.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(intake).as_posix())
    out = main.extract_zip(z, tmp_path / "extracted")
    assert (out / "data.json").is_file()
    assert (out / "files" / "doc-1.pdf").is_file()


# --- determinism ----------------------------------------------------------


def test_import_is_deterministic(tmp_path):
    intake = _make_intake(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    main.main(["import", str(intake), "--case-dir", str(a)])
    main.main(["import", str(intake), "--case-dir", str(b)])

    def dump(case_dir):
        con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
        try:
            rows = {}
            for t in ("cases", "parties", "events", "images", "financial_transactions"):
                rows[t] = con.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
            return rows
        finally:
            con.close()

    assert dump(a) == dump(b)  # ids + created_at (from capturedAt) identical
