"""Transcription = page PNG → Claude vision text, append-only (F4).

The Anthropic client is mocked — no network in CI.
"""

import json
import threading
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
        self._lock = threading.Lock()  # vision tier now runs calls concurrently
        payload = json.dumps({"transcription": transcription, "fidelity": fidelity})
        resp = SimpleNamespace(content=[SimpleNamespace(type="text", text=payload)])
        outer = self

        class _Messages:
            def create(self, **kwargs):
                with outer._lock:
                    outer.calls += 1
                return resp

        self.messages = _Messages()


def _cloud(client):
    """Wrap a mock Anthropic client as the cloud Transcriber transcribe_case takes."""
    return main.CloudTranscriber(client=client)


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
                                     "2026-01-01T00:00:00Z", _cloud(client))
        rows = con.execute(
            "SELECT page_id, rev, source, text, fidelity FROM page_text ORDER BY page_id"
        ).fetchall()
    finally:
        con.close()
    assert stats["pages"] == 2
    assert client.calls == 2
    assert all(r[1] == 0 and r[2] == "ai" for r in rows)  # all rev 0, source ai
    assert all(r[3] == "PETITION ..." and r[4] == 0.9 for r in rows)


def test_force_appends_a_revision(tmp_path):
    case_dir = _exploded_case(tmp_path, pages=1)
    db = case_dir / "lawnlord.duckdb"
    pages = case_dir / "extracted" / "pages"

    con = main.open_case_db(db)
    main.apply_schema(con)
    main.transcribe_case(con, pages, "t0", _cloud(_FakeClient(transcription="FIRST", fidelity=0.8)))
    con.close()

    con = main.open_case_db(db)
    main.transcribe_case(con, pages, "t1",
                         _cloud(_FakeClient(transcription="SECOND", fidelity=0.7)), force=True)
    try:
        revs = con.execute(
            "SELECT rev, text FROM page_text ORDER BY rev"
        ).fetchall()
    finally:
        con.close()
    assert [r[0] for r in revs] == [0, 1]            # appended, not overwritten
    assert revs[0][1] == "FIRST"                     # rev 0 immutable
    assert revs[1][1] == "SECOND"


def test_re_running_skips_already_transcribed_by_default(tmp_path):
    # Resumable: a page that already has text is skipped (only-missing) unless
    # --force. Re-running costs nothing for done pages.
    case_dir = _exploded_case(tmp_path, pages=1)
    db = case_dir / "lawnlord.duckdb"
    pages = case_dir / "extracted" / "pages"

    con = main.open_case_db(db)
    main.apply_schema(con)
    main.transcribe_case(con, pages, "t0", _cloud(_FakeClient(transcription="FIRST", fidelity=0.8)))
    con.close()

    con = main.open_case_db(db)
    client = _FakeClient(transcription="SECOND", fidelity=0.7)
    stats = main.transcribe_case(con, pages, "t1", _cloud(client))
    try:
        revs = con.execute("SELECT rev, text FROM page_text ORDER BY rev").fetchall()
    finally:
        con.close()
    assert client.calls == 0                         # done already → no model call
    assert stats["pages"] == 0
    assert len(stats["skipped_existing"]) == 1
    assert [r[0] for r in revs] == [0]               # no new revision
    assert revs[0][1] == "FIRST"                     # untouched


def test_born_digital_page_uses_pdf_text_layer(tmp_path, monkeypatch):
    # Lever 0: a page with a rich embedded text layer is stored verbatim from the
    # PDF (source='pdf_text', fidelity 1.0, model NULL) with NO model call.
    import lawnlord.transcribe as tx
    case_dir = _exploded_case(tmp_path, pages=1)
    intake_dir = main.find_intake_dir(case_dir)
    monkeypatch.setattr(tx, "extract_pdf_text", lambda _p: ["BORN-DIGITAL TEXT " * 10])

    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    client = _FakeClient()
    stats = main.transcribe_case(con, case_dir / "extracted" / "pages", "t0",
                                 _cloud(client), intake_dir=intake_dir)
    rows = con.execute("SELECT source, text, fidelity, model FROM page_text").fetchall()
    con.close()
    assert client.calls == 0                         # no vision call for born-digital
    assert stats["pdf_text"] == 1 and stats["pages"] == 0
    assert rows[0][0] == "pdf_text"
    assert rows[0][2] == 1.0
    assert rows[0][3] is None                        # model NULL
    assert "BORN-DIGITAL" in rows[0][1]


def test_image_only_page_falls_through_to_vision(tmp_path, monkeypatch):
    # A page with no usable embedded text falls through to the vision tier.
    import lawnlord.transcribe as tx
    case_dir = _exploded_case(tmp_path, pages=1)
    intake_dir = main.find_intake_dir(case_dir)
    monkeypatch.setattr(tx, "extract_pdf_text", lambda _p: [""])  # no text layer

    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    client = _FakeClient(transcription="VISION OCR", fidelity=0.6)
    stats = main.transcribe_case(con, case_dir / "extracted" / "pages", "t0",
                                 _cloud(client), intake_dir=intake_dir)
    rows = con.execute("SELECT source, text FROM page_text").fetchall()
    con.close()
    assert client.calls == 1                         # fell through to vision
    assert stats["pdf_text"] == 0 and stats["pages"] == 1
    assert rows[0][0] == "ai" and rows[0][1] == "VISION OCR"


def test_transcribe_page_sends_image_and_parses(tmp_path):
    case_dir = _exploded_case(tmp_path, pages=1)
    png = next((case_dir / "extracted" / "pages").rglob("*.png"))
    client = _FakeClient(transcription="HELLO", fidelity=0.5)
    out = main.transcribe_page(png, client)
    assert out == {"text": "HELLO", "fidelity": 0.5, "model": main.TRANSCRIBE_MODEL}


def test_cli_transcribe_is_opt_in(tmp_path, capsys, monkeypatch):
    # No ANTHROPIC_API_KEY → clear skip, no crash, no rows. Hermetic: chdir to a
    # dir with no .env so the CLI's .env autoload can't supply a key (a key in a
    # project .env counts as opting in — see _load_dotenv).
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
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


def test_concurrent_vision_preserves_page_order(tmp_path):
    # The vision calls run in a pool; read back in page-id order, every page is
    # present exactly once regardless of completion order.
    case_dir = _exploded_case(tmp_path, pages=5)            # no intake_dir → all vision
    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    client = _FakeClient(transcription="PAGE", fidelity=0.9)
    stats = main.transcribe_case(con, case_dir / "extracted" / "pages", "t0",
                                 _cloud(client), max_workers=4)
    pt_ids = [r[0] for r in con.execute(
        "SELECT page_id FROM page_text ORDER BY page_id").fetchall()]
    page_ids = [r[0] for r in con.execute(
        "SELECT id FROM pages ORDER BY id").fetchall()]
    con.close()
    assert stats["pages"] == 5 and client.calls == 5
    assert pt_ids == page_ids                              # all pages, in id order
    assert len(set(pt_ids)) == 5                           # none duplicated


def test_transient_error_retries_then_succeeds(tmp_path, monkeypatch):
    import lawnlord.transcribe as tx
    monkeypatch.setattr(tx.time, "sleep", lambda _s: None)  # no real backoff wait
    case_dir = _exploded_case(tmp_path, pages=1)

    class FlakyClient:
        def __init__(self):
            self.calls = 0
            self.messages = self

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                exc = RuntimeError("overloaded")
                exc.status_code = 529                       # transient → retried
                raise exc
            return SimpleNamespace(content=[SimpleNamespace(
                type="text", text=json.dumps({"transcription": "OK", "fidelity": 0.7}))])

    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    client = FlakyClient()
    stats = main.transcribe_case(con, case_dir / "extracted" / "pages", "t0", _cloud(client))
    rows = con.execute("SELECT source, text FROM page_text").fetchall()
    con.close()
    assert client.calls == 2                                # failed once, then succeeded
    assert stats["pages"] == 1 and stats["failed"] == []
    assert rows[0] == ("ai", "OK")


def test_permanent_failure_is_reported_not_dropped(tmp_path, monkeypatch):
    # One born-digital page + one image-only page whose vision call always fails.
    # The failure is reported, the run does not abort, and the other page lands.
    import lawnlord.transcribe as tx
    monkeypatch.setattr(tx.time, "sleep", lambda _s: None)
    monkeypatch.setattr(tx, "extract_pdf_text", lambda _p: ["BORN-DIGITAL " * 12, ""])
    case_dir = _exploded_case(tmp_path, pages=2)
    intake_dir = main.find_intake_dir(case_dir)

    class FailingClient:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            raise RuntimeError("permanent boom")            # non-transient → no retry

    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    stats = main.transcribe_case(con, case_dir / "extracted" / "pages", "t0",
                                 _cloud(FailingClient()), intake_dir=intake_dir)
    sources = [r[0] for r in con.execute(
        "SELECT source FROM page_text ORDER BY page_id").fetchall()]
    con.close()
    assert stats["pdf_text"] == 1                           # born-digital page landed
    assert stats["pages"] == 0
    assert len(stats["failed"]) == 1                        # the image-only page
    assert sources == ["pdf_text"]                          # failure dropped no good rows


def test_local_transcriber_calls_ollama(tmp_path, monkeypatch):
    # LocalTranscriber posts the page to Ollama's /api/chat and parses the
    # schema-formatted JSON reply into {text, fidelity, model}.
    import io
    import urllib.request
    import lawnlord.transcribe as tx

    png = next((_exploded_case(tmp_path, pages=1) / "extracted" / "pages").rglob("*.png"))
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        reply = {"message": {"content": json.dumps(
            {"transcription": "LOCAL OCR TEXT", "fidelity": 0.88})}}
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out = tx.LocalTranscriber(model="qwen2.5vl:7b").transcribe(png)
    assert out == {"text": "LOCAL OCR TEXT", "fidelity": 0.88, "model": "qwen2.5vl:7b"}
    assert captured["url"].endswith("/api/chat")
    assert captured["body"]["model"] == "qwen2.5vl:7b"
    assert captured["body"]["messages"][0]["images"]        # the page image was attached


def test_ollama_available_detects_pulled_model(monkeypatch):
    import io
    import urllib.request
    import lawnlord.transcribe as tx

    def tags(_req, timeout=None):
        return io.BytesIO(json.dumps(
            {"models": [{"name": "qwen2.5vl:7b"}, {"name": "minicpm-v:latest"}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", tags)
    assert tx.ollama_available("qwen2.5vl:7b") is True
    assert tx.ollama_available("minicpm-v") is True          # bare name matches :latest
    assert tx.ollama_available("qwen2.5vl") is True          # bare name matches the :7b tag
    assert tx.ollama_available("llava:13b") is False
    # An explicit tag that isn't pulled must NOT pass just because the family is —
    # else the CLI would pick a model Ollama can't serve and never fall back.
    assert tx.ollama_available("qwen2.5vl:3b") is False

    def boom(_req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert tx.ollama_available("qwen2.5vl:7b") is False      # server down → not available


def test_is_transient_classifies_cloud_and_local_errors():
    import socket
    import urllib.error
    import lawnlord.transcribe as tx

    overloaded = RuntimeError("529"); overloaded.status_code = 529
    assert tx._is_transient(overloaded) is True              # cloud overloaded
    http503 = urllib.error.HTTPError("u", 503, "busy", {}, None)
    assert tx._is_transient(http503) is True                 # Ollama warming (.code)
    http404 = urllib.error.HTTPError("u", 404, "no model", {}, None)
    assert tx._is_transient(http404) is False                # model-not-found, not transient
    assert tx._is_transient(urllib.error.URLError("refused")) is True  # connection refused
    assert tx._is_transient(socket.timeout("read timed out")) is True
    assert tx._is_transient(ValueError("bad json")) is False  # non-transient → no retry


def _seed_page_text(con, case_id, page_id, rev, source, fidelity, model, text="L"):
    con.execute(
        "INSERT INTO page_text (case_id, page_id, rev, source, text, fidelity, "
        "model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [case_id, page_id, rev, source, text, fidelity, model, "t0"],
    )


def test_escalate_reruns_only_low_fidelity_model_pages(tmp_path):
    # pdf_text (1.0) and high-fidelity model pages are left alone; only a
    # low-fidelity model page is re-transcribed on cloud, appending a new rev.
    case_dir = _exploded_case(tmp_path, pages=3)
    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    pid = [r[0] for r in con.execute("SELECT id FROM pages ORDER BY id").fetchall()]
    case_id = con.execute("SELECT id FROM cases").fetchone()[0]
    _seed_page_text(con, case_id, pid[0], 0, "pdf_text", 1.0, None)   # born-digital
    _seed_page_text(con, case_id, pid[1], 0, "ai", 0.95, "local")     # good model read
    _seed_page_text(con, case_id, pid[2], 0, "ai", 0.50, "local")     # weak model read

    cloud = _cloud(_FakeClient(transcription="CLOUD", fidelity=0.99))
    stats = main.escalate_case(con, case_dir / "extracted" / "pages", "t1", cloud, threshold=0.9)
    rows = con.execute(
        "SELECT page_id, rev, source, text FROM page_text ORDER BY page_id, rev"
    ).fetchall()
    con.close()

    assert stats["candidates"] == 1 and stats["escalated"] == 1
    by_page = {p: [r for r in rows if r[0] == p] for p in pid}
    assert len(by_page[pid[0]]) == 1                       # pdf_text untouched
    assert len(by_page[pid[1]]) == 1                       # 0.95 >= 0.9 untouched
    assert [r[1] for r in by_page[pid[2]]] == [0, 1]       # weak page got a new rev
    assert by_page[pid[2]][1][2] == "ai" and by_page[pid[2]][1][3] == "CLOUD"


def test_escalation_does_not_re_escalate_cloud_pages(tmp_path):
    # A page whose latest rev the cloud model already produced is NOT re-escalated
    # even if still below T — no unbounded re-billing on genuinely hard pages.
    case_dir = _exploded_case(tmp_path, pages=1)
    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    pid = con.execute("SELECT id FROM pages ORDER BY id").fetchone()[0]
    case_id = con.execute("SELECT id FROM cases").fetchone()[0]
    _seed_page_text(con, case_id, pid, 0, "ai", 0.50, main.TRANSCRIBE_MODEL)  # already cloud
    cloud = _cloud(_FakeClient(transcription="CLOUD2", fidelity=0.6))         # cloud model = TRANSCRIBE_MODEL
    stats = main.escalate_case(con, case_dir / "extracted" / "pages", "t1", cloud, threshold=0.9)
    n = con.execute("SELECT count(*) FROM page_text").fetchone()[0]
    con.close()
    assert stats["candidates"] == 0 and stats["escalated"] == 0
    assert n == 1                                          # no new rev appended


def test_measure_compares_backends_without_writing(tmp_path):
    case_dir = _exploded_case(tmp_path, pages=2)           # no intake_dir → sample all
    con = main.open_case_db(case_dir / "lawnlord.duckdb")
    main.apply_schema(con)
    transcribers = {
        "strong": _cloud(_FakeClient(transcription="x", fidelity=0.95)),
        "weak": _cloud(_FakeClient(transcription="y", fidelity=0.60)),
    }
    result = main.measure_case(con, case_dir / "extracted" / "pages", transcribers, sample=2)
    n_rows = con.execute("SELECT count(*) FROM page_text").fetchone()[0]
    con.close()

    assert result["sampled"] == 2
    assert result["avg_fidelity"]["strong"] == 0.95
    assert result["avg_fidelity"]["weak"] == 0.60
    assert result["escalation_fraction"]["weak"][0.7] == 1.0   # 0.60 < 0.7 everywhere
    assert result["escalation_fraction"]["strong"][0.7] == 0.0
    assert n_rows == 0                                          # read-only: no page_text writes
