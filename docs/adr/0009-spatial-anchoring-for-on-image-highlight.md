# ADR-0009: Capture optional spatial anchors so divergence can be highlighted on the page image

Status: Accepted
Date: 2026-06-22

## Context

The headline feature highlights where readings disagree **on the page image**, not
only in the text viewer. That needs to know *where on the page* a divergent span sits
— per-span bounding boxes — but transcription today is plain text with no coordinates.
The coordinate sources are heterogeneous and quality-variable:

- **PDF text layer (born-digital):** `pypdfium2` exposes per-character/word geometry —
  precise, free, deterministic.
- **Cloud vision (Claude):** can be prompted to return boxes; recent models return
  pixel-accurate coordinates. Workable, at added prompt/parse cost.
- **Local vision models:** `qwen2.5vl` grounds well; `minicpm-v` / `granite` are weak
  or unreliable at boxes. Some columns will have no usable coordinates.

A second hard step follows getting boxes: **aligning the text diff (ADR-0008) to those
boxes** so "token X differs" becomes "this region on the image."

## Decision

Capture an **optional, additive spatial layer** — bounding boxes per text span,
anchored to a source row's stable `id` (a transcription variation's `id` per ADR-0005
today; an entity's `id` later). Populate it from PDF geometry for `pdf_text`, and from
model-returned boxes for vision backends that support grounding. A row with **no
reliable boxes degrades gracefully to text-only highlighting** — we never fabricate a
region. On-image highlighting maps spans to their boxes and renders the link.

This spatial layer and the highlight/click-to-locate renderer built on it are a
**general page-region primitive**, deliberately not transcription-specific: any object
that can name a page span — a citation, claim, defense, or statute surfaced by the
analysis layer (#38, #118) — reuses the same anchors and the same on-image
highlighting. Transcription divergence (mapping the ADR-0008 diff spans onto boxes) is
simply its **first consumer**.

## Consequences

- Enables on-image difference highlighting where coordinates exist; honest text-only
  fallback where they do not (coverage is surfaced, not hidden).
- The span/box layer doubles as the span-level provenance (artifact/page/span) the
  future entity graph (#38) needs.
- Additive: no change to the mirror. Box coordinates from a model are non-deterministic
  like the model text — captured append-only as returned; only ids/ordering/structure
  are deterministic.
- Cost: vision prompts that also request layout are heavier; box quality varies by
  model and must be treated as a quality signal, not ground truth.

## Alternatives considered

- **Run a positional OCR engine (PaddleOCR/docTR) and align every model to it** —
  deferred: a heavy new dependency; revisit only if model-returned boxes prove too
  unreliable to align.
- **Require every model to produce boxes** — rejected: would exclude local models that
  transcribe well but ground poorly, defeating the comparison.
- **Skip on-image highlight, text-diff only** — rejected: that is the wow feature.

## Implementation notes (first slice, #128)

The decisions this ADR left open, pinned when the first slice landed:

- **Table** `page_regions` (schema v11): `id`, `case_id`, `page_id`, `anchor_id`, `anchor_kind`,
  `span_index`, `char_start`, `char_end`, `x0/y0/x1/y1`, `origin`, `confidence`, `created_at`. The
  generic `(anchor_kind, anchor_id)` pair — `page_text` today, `entity` later — is what makes it a
  reusable primitive rather than transcription-specific.
- **Coordinates**: normalized `[0, 1]` with a **top-left origin**, not PNG pixels or PDF points —
  resolution-independent, so they overlay the rendered PNG at any DPI and match the browser/CSS axis.
  pypdfium2 returns points with a bottom-left origin; capture converts via the page's `get_size()`.
- **Span unit**: one region per **whitespace token** of the anchor text (`char_start`/`char_end` carve
  it out), matching the export layer's divergence token spans so a divergence span maps onto regions
  with no re-derivation. A token is single-line, so its box is the union of its glyph boxes.
- **Determinism**: `id = sha256(anchor_kind|anchor_id|span_index)` — hashes structure only, never the
  (possibly model-supplied, non-deterministic) coordinates. Capture rebuilds the `pdf_text` origin
  idempotently and leaves any `model` rows untouched.
- **Never fabricate**: PDF geometry is captured only when the stored anchor text still matches the
  PDF's freshly-read text layer (and the glyph-box count aligns 1:1); otherwise the page is skipped.
- **Deferred to #128b**: vision-model-returned boxes (`origin='model'`). No backend requests boxes
  today, so the model path is a documented no-op — never a fabricated region. Page **rotation** is a
  known limitation (geometry captured for rotation-0 born-digital pages).
