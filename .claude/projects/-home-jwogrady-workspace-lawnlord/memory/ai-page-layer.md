---
name: ai-page-layer
description: AI per-page pass (Claude vision) — transcription→revision, summary/analysis→#28 proposal; cloud opt-in
metadata:
  type: project
---

The Enhanced reviewer can run one Claude vision pass per page (`lawnlord ai-page`, web `/api/ai-page`) that returns three things, each routed to the right layer:
- **transcription** → appended to the page's append-only revision history with source `ai` (rev 0, the original extraction, stays immutable)
- **summary** + **analysis** (docType/parties/dates/amounts/keyPoints/flags) → a [[two-mode-original-enhanced]] Enhanced **#28 proposal**: Pending until the human accepts/declines. The tool proposes, never concludes.

Decisions made with the user:
- **Cloud opt-in.** Uses the Anthropic API (sends the page image/text to the cloud) — the user explicitly accepted this for their own sensitive case data. Needs `ANTHROPIC_API_KEY` in the env that runs `bun dev`. Model via `LAWNLORD_AI_MODEL` (default `claude-sonnet-4-6`).
- **Transcribe the image, don't correct OCR.** Output tokens dominate cost and are identical either way, so the image adds only ~pennies across a case, and it recovers caption layout / dropped text OCR can't. OCR is an optional hint only (off by default).

**Why:** evidence-grade text + additive analysis the human controls, without weakening the immutable record.
**How to apply:** new AI outputs are additive — transcription is a revision (never overwrites rev 0), analysis is a proposal (never auto-truth). Engine stays in Python; web shells out (mirrors `ocr-page`).
