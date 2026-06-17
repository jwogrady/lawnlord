"""AI page understanding: transcribe + summarize + analyze in one pass.

These tests never hit the network — the Anthropic client is stubbed — so they
verify the wiring (image encoding, the forced tool call, JSON-only CLI output,
and the actionable errors) without an API key.
"""

import json
import sys
import types

import fitz
import pytest

import lawnlord as main
from lawnlord import ai, cli


def _png(tmp_path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "FILED PAGE")
    png = tmp_path / "page.png"
    doc[0].get_pixmap().save(png)
    doc.close()
    return png


class _ToolBlock:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


def _stub_anthropic(monkeypatch, payload, capture=None):
    """Install a fake `anthropic` module whose client returns one tool_use block."""

    class _Messages:
        def create(self, **kwargs):
            if capture is not None:
                capture.update(kwargs)
            return types.SimpleNamespace(content=[_ToolBlock(payload)])

    class _Anthropic:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    monkeypatch.setitem(
        sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_Anthropic)
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def test_analyze_page_returns_structured_result(tmp_path, monkeypatch):
    payload = {
        "transcription": "PLAINTIFF'S ORIGINAL PETITION ...",
        "summary": "The petition's caption and parties.",
        "analysis": {"docType": "Original Petition", "keyPoints": ["names parties"]},
    }
    capture: dict = {}
    _stub_anthropic(monkeypatch, payload, capture)

    out = main.analyze_page(str(_png(tmp_path)))

    assert out["transcription"].startswith("PLAINTIFF")
    assert out["summary"] and out["analysis"]["docType"] == "Original Petition"
    assert out["model"]  # the model used is recorded on the result
    # the call forces the page_analysis tool and sends an image block
    assert capture["tool_choice"] == {"type": "tool", "name": "page_analysis"}
    blocks = capture["messages"][0]["content"]
    assert any(b.get("type") == "image" for b in blocks)


def test_analyze_page_requires_api_key(tmp_path, monkeypatch):
    # No key → a clear, actionable error, not a stack trace from the SDK.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setitem(
        sys.modules, "anthropic", types.SimpleNamespace(Anthropic=object)
    )
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        main.analyze_page(str(_png(tmp_path)))


def test_model_override_wins(tmp_path, monkeypatch):
    capture: dict = {}
    _stub_anthropic(monkeypatch, {"transcription": "", "summary": "", "analysis": {}}, capture)
    main.analyze_page(str(_png(tmp_path)), model="claude-test-model")
    assert capture["model"] == "claude-test-model"


def test_ai_page_cli_emits_only_json(tmp_path, monkeypatch, capsys):
    payload = {
        "transcription": "T",
        "summary": "S",
        "analysis": {"docType": "x", "keyPoints": []},
    }
    _stub_anthropic(monkeypatch, payload)
    cli.main(["ai-page", str(_png(tmp_path))])
    out = json.loads(capsys.readouterr().out)
    assert out["transcription"] == "T" and out["summary"] == "S"
    assert out["analysis"]["docType"] == "x" and out["model"]


def test_default_model_is_exported():
    assert main.AI_DEFAULT_MODEL == ai.DEFAULT_MODEL and ai.DEFAULT_MODEL
