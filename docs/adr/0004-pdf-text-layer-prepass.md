# ADR-0004: Embedded PDF text-layer pre-pass before any vision tier

Status: Accepted
Date: 2026-06-22

## Context

ADR-0001/0002 commit to a local-GPU vision tier (with cloud escalation) to
transcribe page PNGs. That framing assumes every page must be recognized from
pixels. A per-page measurement of the working case contradicts that assumption:
**149 of 255 pages are born-digital and carry a rich embedded text layer; 106 are
scanned/image-only** (`< 100` non-whitespace chars). The image bulk is
concentrated in two large filings — `doc-25856216` (Motion for Summary Judgment,
121 pages, 94 image-only) and `doc-25980946` (Answer, 64 pages, 8 image-only) —
with `doc-24775937`/`doc-24775944` adding 2 each. No PDF is *fully* image-only:
every file's caption page is born-digital, which is why an earlier per-*file*
count overstated the win as "20/22 PDFs / ~248 pages". See
`docs/problem-transcription-efficiency.md` (lever 0).

For a born-digital page the PDF *already contains the exact text*. Re-recognizing
it with a vision model is wasted compute and **worse output** — it introduces OCR
error over ground truth. `pypdfium2` is already a dependency (it renders pages in
`explode.py`) and exposes per-page text extraction
(`get_textpage().get_text_range()`), so reading the existing layer needs no new
dependency and is **free and deterministic**.

This is distinct from the "local OCR" alternative ADR-0002 reserved: that meant
re-recognizing pixels with PaddleOCR/docTR; this reads the file's own text.

## Decision

Add a **text-layer pre-pass** as the first transcription source, ahead of any
vision tier (local or cloud):

- For each page, extract the embedded text via `pypdfium2`. If the page has
  usable embedded text (above a char-density threshold — the measurement's
  `thin`/`image-only` rule), write it to `page_text` with `source='pdf_text'`,
  `fidelity=1.0`, and `model=NULL`. No model call.
- Pages with no/usable-thin embedded text fall through to the vision tier
  (ADR-0001) — local-first, with fidelity-gated cloud escalation (ADR-0001 / #106).
- The pre-pass composes with resume (#103): a page that already has a revision is
  skipped; `--force` re-runs and appends a new `rev`.
- The pre-pass lives in the **transcribe** step (it is a transcription *source*),
  not `explode` — `explode` stays focused on deterministic PNG rendering. The
  mirror is never written; rows are stamped from `generated_at`.

## Consequences

- **Easier:** the first full run drops from 255 model calls to **~106** (this
  case): 149 born-digital pages land straight from the text layer, before any
  local/cloud decision — near-instant and near-free, and *more* accurate on those
  pages (exact text, no OCR error). The vision tier still carries the ~106
  image-only pages, so the local-vs-Opus measurement (#106) remains the load-
  bearing lever for this case, not an afterthought — the pre-pass roughly halves
  its input rather than reducing it to a handful.
- **Harder:** a `source` column now carries `pdf_text` as well as `ai`; exports
  and the viewer should surface provenance (and may show `pdf_text` differently
  from a model transcription). Embedded text reading-order can occasionally be
  imperfect for complex multi-column/stamped forms — the char-density gate is a
  coarse filter, so a page with a misleading thin/garbled layer should fall
  through to vision rather than be trusted blindly.
- **Invariants preserved:** `page_text` stays append-only; mirror never written;
  stable insert ordering; `generated_at` (not wall-clock) stamps every row;
  deterministic (no model, byte-stable extraction).

## Alternatives considered

- **Vision-only for everything (status quo / ADR-0001 as written).** Uniform code
  path, but pays a model to re-OCR text that already exists exactly, and is less
  accurate on the 149 born-digital pages. Rejected as the default.
- **Use embedded text only as a fidelity cross-check, still OCR every page.**
  Keeps one path and gives an objective fidelity signal, but throws away the free
  ground-truth and the ~58% cost/time win (149 of 255 pages). Rejected; the
  cross-check is a possible future refinement, not a reason to re-OCR.
- **Put the pre-pass in `explode`.** Tempting since it reads PDFs there, but it
  would couple rendering to the text layer and write a transcription artifact from
  the render step. Rejected: `explode` renders; `transcribe` sources text.
