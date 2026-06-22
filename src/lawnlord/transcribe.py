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
import pypdfium2 as pdfium

# Below this many non-whitespace characters, a page's embedded text layer is
# treated as absent (scanned/image-only) and the page falls through to the
# vision tier. The working case shows a clean gap around here — pages carry
# either <54 chars (stamps on image pages) or >=100 (born-digital text), nothing
# between — so the exact cutoff in (53, 100] is not sensitive.
MIN_PDF_TEXT_CHARS = 100

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


def extract_pdf_text(pdf_path: str | Path) -> list[str]:
    """Embedded text of each page of ``pdf_path`` (list index = 0-based page
    index), read via pypdfium2 — free, deterministic, and the page's *exact* text
    when it is born-digital. A page with no text layer yields an empty/near-empty
    string: the signal that it is scanned/image-only and needs the vision tier."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        texts: list[str] = []
        for i in range(len(pdf)):
            page = pdf[i]
            textpage = page.get_textpage()
            try:
                texts.append(textpage.get_text_range())
            finally:
                textpage.close()
                page.close()
        return texts
    finally:
        pdf.close()


def _embedded_text(intake_dir, intake_path, image_id, page_number, cache) -> str | None:
    """Embedded text for one page (1-based ``page_number``) of its source PDF, or
    ``None`` when the pre-pass cannot run (no intake dir, missing or unreadable
    PDF, or index out of range) — in which case the page falls through to the
    vision tier. Caches per-image extraction so each PDF is opened at most once."""
    if intake_dir is None or intake_path is None:
        return None
    if image_id not in cache:
        pdf_path = intake_dir / intake_path
        try:
            cache[image_id] = extract_pdf_text(pdf_path) if pdf_path.exists() else None
        except Exception:
            # A corrupt/encrypted/unreadable PDF has no usable text layer for our
            # purposes: degrade to the vision tier rather than abort the run.
            cache[image_id] = None
    texts = cache[image_id]
    if texts is None:
        return None
    idx = page_number - 1
    return texts[idx] if 0 <= idx < len(texts) else None


def transcribe_case(
    con: duckdb.DuckDBPyConnection,
    pages_dir: str | Path,
    generated_at: str,
    client,
    model: str = DEFAULT_MODEL,
    force: bool = False,
    intake_dir: str | Path | None = None,
) -> dict:
    """Transcribe pages in the `pages` table, appending to `page_text`.

    Two sources, cheapest first. **Text-layer pre-pass (ADR-0004):** when
    ``intake_dir`` is given, a born-digital page's exact text is read straight
    from its PDF (``source='pdf_text'``, ``fidelity=1.0``, no model call). Only a
    page with no usable embedded text falls through to the **vision tier**
    (``transcribe_page`` → ``source='ai'``), which needs the rendered PNG under
    ``pages_dir``.

    Resumable by default: a page that already has a `page_text` row is **skipped**
    (only-missing), so re-running — or recovering an interrupted run — costs only
    the pages still to do. ``force=True`` re-runs every page, appending the next
    rev (rev 0 stays immutable; revisions are never overwritten).
    """
    pages_dir = Path(pages_dir)
    intake_dir = Path(intake_dir) if intake_dir is not None else None
    rows = con.execute(
        "SELECT p.id, p.case_id, p.page_image_path, p.image_id, p.page_number, "
        "i.intake_path FROM pages p JOIN images i ON i.id = p.image_id "
        "ORDER BY p.id"
    ).fetchall()

    done = 0
    pdf_text = 0
    fidelity_sum = 0.0
    skipped: list[str] = []
    skipped_existing: list[str] = []
    text_cache: dict[str, list[str] | None] = {}
    for page_id, case_id, rel, image_id, page_number, intake_path in rows:
        prev = con.execute(
            "SELECT max(rev) FROM page_text WHERE page_id = ?", [page_id]
        ).fetchone()[0]
        if prev is not None and not force:
            skipped_existing.append(page_id)
            continue
        rev = 0 if prev is None else prev + 1

        # Lever 0: a born-digital page already holds its exact text — store it
        # verbatim (fidelity 1.0, no model). Distinct from OCR; see ADR-0004.
        embedded = _embedded_text(intake_dir, intake_path, image_id, page_number, text_cache)
        if embedded is not None and len(embedded.strip()) >= MIN_PDF_TEXT_CHARS:
            con.execute(
                "INSERT INTO page_text (case_id, page_id, rev, source, text, "
                "fidelity, model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [case_id, page_id, rev, "pdf_text", embedded, 1.0, None, generated_at],
            )
            pdf_text += 1
            continue

        # No usable text layer → vision tier (needs the rendered PNG).
        png = pages_dir / rel
        if not png.exists():
            skipped.append(rel)
            continue
        result = transcribe_page(png, client, model=model)
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
        "pdf_text": pdf_text,
        "avg_fidelity": (fidelity_sum / done) if done else 0.0,
        "skipped": skipped,
        "skipped_existing": skipped_existing,
    }
