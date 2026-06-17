"""AI page understanding: transcribe, summarize, and analyze a filed page.

A vision-capable Claude model reads the page **image** (the court's own filing,
not a render of our text) and returns three things in one pass:

- ``transcription`` — a faithful, well-structured transcription of the page.
  This is evidence-grade text: it preserves caption blocks, headings, spacing,
  amounts, and dates that OCR garbles. The caller appends it to the page's
  revision history (source ``ai``); the original extraction (rev 0) is never
  touched.
- ``summary`` — a short plain-language description of what the page is.
- ``analysis`` — structured, additive observations (doc type, parties, dates,
  amounts, key points, flags). Per the accept/decline model, this is a
  PROPOSAL: it stays Pending until a human accepts or declines it. The tool
  surfaces and proposes; it never renders a legal conclusion.

This sends the page image (and any prior extracted text) to Anthropic's API, so
it is opt-in per page. Requires ``ANTHROPIC_API_KEY`` in the environment. The
model is configurable via ``LAWNLORD_AI_MODEL`` (default: a capable vision
model); quality matters more than cost here because the output is read by a
human preparing a case.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

# A capable vision model by default; override with LAWNLORD_AI_MODEL (e.g. a
# cheaper model for bulk passes, or the latest Opus for the hardest pages).
DEFAULT_MODEL = "claude-sonnet-4-6"

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# The structured output we force the model to return — one tool call, validated
# by the schema so we never parse free-form prose.
PAGE_ANALYSIS_TOOL = {
    "name": "page_analysis",
    "description": "Return the transcription, summary, and analysis of one filed page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "transcription": {
                "type": "string",
                "description": (
                    "Faithful, readable transcription of ALL text on the page. "
                    "Preserve structure: caption block, headings, numbered "
                    "sections, signature lines, dates, dollar amounts. Do not "
                    "summarize, correct, or add anything not on the page. Render "
                    "the § section symbol as §, not S."
                ),
            },
            "summary": {
                "type": "string",
                "description": "One to three plain-language sentences: what this page is and does.",
            },
            "analysis": {
                "type": "object",
                "description": "Additive, factual observations — NOT legal conclusions.",
                "properties": {
                    "docType": {
                        "type": "string",
                        "description": "What kind of document/section this page is (e.g. 'Original Petition — caption + parties').",
                    },
                    "parties": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names of parties/people/entities mentioned on the page.",
                    },
                    "dates": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Dates appearing on the page, verbatim.",
                    },
                    "amounts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Dollar amounts appearing on the page, verbatim.",
                    },
                    "keyPoints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The substantive assertions/claims/requests stated on the page.",
                    },
                    "flags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Items a case preparer should notice: service of "
                            "process, jurisdiction/venue, deadlines, fees vs. "
                            "dues, amounts owed. Observation only, never a ruling."
                        ),
                    },
                },
                "required": ["docType", "keyPoints"],
            },
        },
        "required": ["transcription", "summary", "analysis"],
    },
}

_PROMPT = (
    "You are assisting a person preparing their own defense in the case shown. "
    "Read the attached page image of a court filing and call the page_analysis "
    "tool. Transcribe faithfully (do not summarize in the transcription), then "
    "give a short summary and structured analysis. The analysis is a proposal a "
    "human will accept or decline — state observations, never legal conclusions."
)


def _media_type(path: str) -> str:
    return _MEDIA_TYPES.get(Path(path).suffix.lower(), "image/png")


def analyze_page(
    image_path: str,
    *,
    extracted_text: str | None = None,
    model: str | None = None,
) -> dict:
    """Transcribe, summarize, and analyze one page image in a single call.

    Returns ``{"transcription", "summary", "analysis", "model"}``. Raises a
    clear error if the ``anthropic`` SDK is missing or ``ANTHROPIC_API_KEY`` is
    not set, so the failure is actionable rather than a stack trace.
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise RuntimeError(
            "AI page understanding requires the 'anthropic' package "
            "(`uv add anthropic`)."
        ) from exc

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export your Anthropic API key to "
            "enable AI transcription/analysis (this sends the page image to the "
            "Anthropic API)."
        )

    model = model or os.environ.get("LAWNLORD_AI_MODEL") or DEFAULT_MODEL
    data = base64.standard_b64encode(Path(image_path).read_bytes()).decode("ascii")

    content: list[dict] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _media_type(image_path),
                "data": data,
            },
        },
        {"type": "text", "text": _PROMPT},
    ]
    if extracted_text:
        content.append(
            {
                "type": "text",
                "text": (
                    "For reference only, here is the current (possibly imperfect) "
                    f"extracted text for this page:\n\n{extracted_text}"
                ),
            }
        )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        tools=[PAGE_ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "page_analysis"},
        messages=[{"role": "user", "content": content}],
    )
    for block in message.content:
        if getattr(block, "type", None) == "tool_use":
            result = dict(block.input)
            result["model"] = model
            return result
    raise RuntimeError("Model did not return a page_analysis tool call.")
