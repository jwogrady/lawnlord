"""The Actual-lens export reads the DuckDB mirror into the viewer payload (F2)."""

import json

import lawnlord as main

_CASE = {
    "caseNumber": "99-00-12345",
    "caseType": "Foreclosure - Other",
    "dateFiled": "01/02/2025",
    "location": "284th Judicial District Court",
    "parties": [
        {"name": "Doe, John", "role": "Defendant", "representation": ["Pro Se", "Town, TX"]},
        {"name": "ACME HOA", "role": "Plaintiff", "representation": ["Jane Lawyer Retained"]},
    ],
    "documents": [
        {"Image": "Plaintiff's Original Petition", "Page Count": "6", "date": "01/02/2025",
         "event": "E-Filed Original Petition", "file": "files/doc-1.pdf"},
    ],
    "registerOfActions": [
        {"date": "01/02/2025", "event": "Original Petition (OCA)", "section": "other events and hearings"},
        {"date": "01/02/2025", "event": "E-Filed Original Petition",
         "section": "other events and hearings", "documents": ["files/doc-1.pdf"]},
    ],
    "financial": {"assessedTo": "Plaintiff ACME HOA", "totalAssessment": "366.00",
                  "totalPayments": "366.00", "balanceDue": "0.00", "balanceAsOf": "06/20/2026",
                  "transactions": []},
}

_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "array",
    "items": {"type": "object", "properties": {"caseNumber": {"type": "string"}},
              "required": ["caseNumber"]},
}


def _import(tmp_path, case=None):
    d = tmp_path / "intake"
    (d / "files").mkdir(parents=True)
    (d / "data.json").write_text(json.dumps([case or _CASE]), encoding="utf-8")
    (d / "schema.json").write_text(json.dumps(_SCHEMA), encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({"capturedAt": "2026-01-01T00:00:00Z"}), encoding="utf-8")
    (d / "files" / "doc-1.pdf").write_bytes(b"%PDF-1.4\n%x\n%%EOF")
    case_dir = tmp_path / "out"
    main.main(["import", str(d), "--case-dir", str(case_dir)])
    return case_dir


def test_export_actual_shape(tmp_path):
    case_dir = _import(tmp_path)
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        payload = main.export_actual(con)
    finally:
        con.close()

    assert payload["case"]["number"] == "99-00-12345"
    assert payload["case"]["court"] == "284th Judicial District Court"
    assert {p["name"] for p in payload["parties"]} == {"Doe, John", "ACME HOA"}
    assert len(payload["documents"]) == 1
    assert payload["documents"][0]["declaredPageCount"] == 6

    roa = payload["registerOfActions"]
    assert len(roa) == 2
    # The e-filed petition entry carries its filed document; the OCA entry does not.
    with_docs = [e for e in roa if e["documents"]]
    assert len(with_docs) == 1
    assert with_docs[0]["documents"][0]["filename"] == "doc-1.pdf"


def test_export_actual_carries_source_url_provenance(tmp_path):
    case = json.loads(json.dumps(_CASE))
    case["documents"][0]["url"] = "https://portal.example/img/doc-1"
    case_dir = _import(tmp_path, case=case)
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        payload = main.export_actual(con)
    finally:
        con.close()
    # The case header exposes the existing case-level provenance columns so the
    # viewer can show where the case came from (mapped elsewhere; here just that
    # the keys are returned, not omitted).
    assert "sourceUrl" in payload["case"]
    assert "lastRefreshed" in payload["case"]
    # Each document carries its own source URL.
    assert payload["documents"][0]["sourceUrl"] == "https://portal.example/img/doc-1"


def test_export_actual_document_without_url_exports_null(tmp_path):
    case_dir = _import(tmp_path)  # _CASE's document declares no url
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        payload = main.export_actual(con)
    finally:
        con.close()
    doc = payload["documents"][0]
    assert "sourceUrl" in doc  # present, not omitted
    assert doc["sourceUrl"] is None  # null, not a placeholder


def test_export_actual_cli_emits_json(tmp_path, capsys):
    case_dir = _import(tmp_path)
    capsys.readouterr()  # discard the import command's table output
    main.main(["export-actual", "--case-dir", str(case_dir)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["case"]["number"] == "99-00-12345"
    assert payload["registerOfActions"]
