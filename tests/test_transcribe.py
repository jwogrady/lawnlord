"""Transcription = page PNG → Claude vision text, append-only (F4).

The Anthropic client is mocked — no network in CI.
"""

import json
from types import SimpleNamespace

from pypdf import PdfWriter

import lawnlord as main

_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "array",
    "items": {"type": "object", "properties": {"caseNumber": {"type": "string"}},
              "required": ["caseNumber"]},
}
_CASE = {
    "caseNumber": "99-00-12345", "caseType": "F", "dateFiled": "01/02/2025", "location": "X",
    "parties": [{"name": "Doe", "role": "Defendant", "representation": ["Pro Se"]}],
    "documents": [{"Image": "Petition", "Page Count": "2", "date": "01/02/2025",
                   "event": "Filed", "file": "files/doc-1.pdf"}],
    "registerOfActions": [{"date": "01/02/2025", "event": "Filed", "section": "e",
                           "documents": ["files/doc-1.pdf"]}],
    "financial": {},
}


class _FakeClient:
    """Stands in for anthropic.Anthropic — returns canned JSON, counts calls."""

    def __init__(self, transcription="TRANSCRIBED TEXT", fidelity=0.95):
        self.calls = 0
        payload = json.dumps({"transcription": transcription, "fidelity": fidelity})
        resp = SimpleNamespace(content=[SimpleNamespace(type="text", text=payload)])
        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls += 1
                return resp

        self.messages = _Messages()


def _exploded_case(tmp_path, pages=2):
    d = tmp_path / "intake"
    (d / "files").mkdir(parents=True)
    d.joinpath("data.json").write_text(json.dumps([_CASE]), encoding="utf-8")
    d.joinpath("schema.json").write_text(json.dumps(_SCHEMA), encoding="utf-8")
    d.joinpath("manifest.json").write_text(json.dumps({"capturedAt": "2026-01-01T00:00:00Z"}), encoding="utf-8")
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    with open(d / "files" / "doc-1.pdf", "wb") as f:
        w.write(f)
    case_dir = tmp_path / "out"
    main.main(["import", str(d), "--case-dir", str(case_dir)])
    main.main(["explode", "--case-dir", str(case_dir)])
    return case_dir


def test_transcribe_case_appends_rev0(tmp_path):
    case_dir = _exploded_case(tmp_path, pages=2)
    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    client = _FakeClient(transcription="PETITION ...", fidelity=0.9)
    try:
        stats = main.transcribe_case(con, case_dir / "extracted" / "pages",
                                     "2026-01-01T00:00:00Z", client)
        rows = con.execute(
            "SELECT page_id, rev, source, text, fidelity FROM page_text ORDER BY page_id"
        ).fetchall()
    finally:
        con.close()
    assert stats["pages"] == 2
    assert client.calls == 2
    assert all(r[1] == 0 and r[2] == "ai" for r in rows)  # all rev 0, source ai
    assert all(r[3] == "PETITION ..." and r[4] == 0.9 for r in rows)


def test_re_running_appends_a_revision(tmp_path):
    case_dir = _exploded_case(tmp_path, pages=1)
    db = case_dir / "lawnlord.duckdb"
    pages = case_dir / "extracted" / "pages"

    con = main.open_case_db(db)
    main.apply_schema(con)
    main.transcribe_case(con, pages, "t0", _FakeClient(transcription="FIRST", fidelity=0.8))
    con.close()

    con = main.open_case_db(db)
    main.transcribe_case(con, pages, "t1", _FakeClient(transcription="SECOND", fidelity=0.7))
    try:
        revs = con.execute(
            "SELECT rev, text FROM page_text ORDER BY rev"
        ).fetchall()
    finally:
        con.close()
    assert [r[0] for r in revs] == [0, 1]            # appended, not overwritten
    assert revs[0][1] == "FIRST"                     # rev 0 immutable
    assert revs[1][1] == "SECOND"


def test_transcribe_page_sends_image_and_parses(tmp_path):
    case_dir = _exploded_case(tmp_path, pages=1)
    png = next((case_dir / "extracted" / "pages").rglob("*.png"))
    client = _FakeClient(transcription="HELLO", fidelity=0.5)
    out = main.transcribe_page(png, client)
    assert out == {"text": "HELLO", "fidelity": 0.5, "model": main.TRANSCRIBE_MODEL}


def test_cli_transcribe_is_opt_in(tmp_path, capsys, monkeypatch):
    # No ANTHROPIC_API_KEY → clear skip, no crash, no rows.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    case_dir = _exploded_case(tmp_path, pages=1)
    capsys.readouterr()
    main.main(["transcribe", "--case-dir", str(case_dir)])
    out = capsys.readouterr().out
    assert "opt-in" in out
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM page_text").fetchone()[0] == 0
    finally:
        con.close()
