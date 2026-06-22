"""Transcribe each filed page from its PNG render using Claude vision (F4).

PNG-per-page → AI transcription (measured materially more accurate than OCR).
This is the **additive** text layer on the Exploded view: it reads the `pages`
table's PNGs and appends to `page_text` — rev 0 is the original transcription
(immutable); a re-run appends a new revision, never overwriting. Each row carries
a **fidelity** signal (the model's self-assessment of how completely it could read
the page) — the honest reframing of the removed page-score (#70).

Cloud opt-in: the CLI runs this only when ``ANTHROPIC_API_KEY`` is set. The
Anthropic client is injectable so tests mock it (no network in CI).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import duckdb

# Claude vision model. Confirmed current via the claude-api reference; override
# with --model. Adaptive thinking is off by default on this model (omitted).
DEFAULT_MODEL = "claude-opus-4-8"

# Structured output: the model returns the page text + a 0..1 fidelity estimate.
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "transcription": {"type": "string"},
        "fidelity": {"type": "number"},
    },
    "required": ["transcription", "fidelity"],
    "additionalProperties": False,
}

_PROMPT = (
    "Transcribe this filed court document page verbatim — preserve the wording, "
    "line breaks, and reading order; do not summarize, correct, or omit anything. "
    "Return JSON with `transcription` (the full page text) and `fidelity` (0.0–1.0: "
    "your confidence the transcription is complete and accurate given how legible "
    "the image is)."
)


def make_client():
    """The default Anthropic client (reads ANTHROPIC_API_KEY from the env)."""
    import anthropic

    return anthropic.Anthropic()


def _b64_png(path: str | Path) -> str:
    return base64.standard_b64encode(Path(path).read_bytes()).decode("utf-8")


def transcribe_page(png_path: str | Path, client, model: str = DEFAULT_MODEL) -> dict:
    """Transcribe one page PNG via Claude vision. ``client`` is any object with an
    ``messages.create`` compatible with the Anthropic SDK (injected for tests).
    Returns ``{text, fidelity, model}``."""
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": _b64_png(png_path),
                        },
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
    )
    text = next(b.text for b in resp.content if getattr(b, "type", None) == "text")
    data = json.loads(text)
    return {
        "text": data.get("transcription", ""),
        "fidelity": float(data.get("fidelity", 0.0)),
        "model": model,
    }


def transcribe_case(
    con: duckdb.DuckDBPyConnection,
    pages_dir: str | Path,
    generated_at: str,
    client,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Transcribe every page in the `pages` table, appending to `page_text`.

    ``pages_dir`` is where the page PNGs live (the explode step's output root);
    ``page_image_path`` is relative to it. Each page gets the next rev (rev 0 the
    first time), so re-running appends rather than overwriting.
    """
    pages_dir = Path(pages_dir)
    rows = con.execute(
        "SELECT id, case_id, page_image_path FROM pages ORDER BY id"
    ).fetchall()

    done = 0
    fidelity_sum = 0.0
    skipped: list[str] = []
    for page_id, case_id, rel in rows:
        png = pages_dir / rel
        if not png.exists():
            skipped.append(rel)
            continue
        result = transcribe_page(png, client, model=model)
        prev = con.execute(
            "SELECT max(rev) FROM page_text WHERE page_id = ?", [page_id]
        ).fetchone()[0]
        rev = 0 if prev is None else prev + 1
        con.execute(
            "INSERT INTO page_text (case_id, page_id, rev, source, text, fidelity, "
            "model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [case_id, page_id, rev, "ai", result["text"], result["fidelity"],
             result["model"], generated_at],
        )
        done += 1
        fidelity_sum += result["fidelity"]

    return {
        "pages": done,
        "avg_fidelity": (fidelity_sum / done) if done else 0.0,
        "skipped": skipped,
    }
