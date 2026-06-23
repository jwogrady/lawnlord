# ADR-0006: Transcribe every page with every available model, not cheapest-first

Status: Accepted
Date: 2026-06-22

## Context

ADR-0004 established a cheapest-first policy: a born-digital page's exact text is
read from the PDF layer and the page **skips the vision tier entirely** — running a
vision model on a page whose text is already exact was framed as wasted compute that
only introduces OCR error over ground truth.

That holds when the goal is *a* transcription. It is wrong when the goal is
*confidence* in the transcription. `docs/problem-transcription-corpus.md` reframes the
goal: the corpus must let a human verify the text, which means each model's reading
must be checked **against the PDF text layer** and against the other models. A
born-digital page with no AI reading has nothing to diff against — the text layer
would have to be trusted on faith, which is the original problem.

## Decision

`transcribe` runs the PDF-text-layer pre-pass **and** every available vision model on
**every** page; nothing is skipped because a text layer exists. Local vision models
are **discovered** from the Ollama install (vision capability), never hardcoded; the
cloud model is added when opted in. Skip/resume and revision counting are per
`(page, source, model)` (per ADR-0005), so a re-run only fills missing variations.

## Consequences

- Every page can show the full comparison grid — canonical source, text layer, and
  every model — so divergence and the confidence gauges have real inputs everywhere,
  including born-digital pages.
- Cost rises: roughly `models × pages` vision calls instead of `models × image-only
  pages`. Accepted, and mitigated by (a) local-first inference being free, and (b)
  per-variation resume making re-runs incremental.
- This **retires the cheapest-first short-circuit of ADR-0004**. The text-layer
  *extraction* ADR-0004 introduced is retained — it is now simply one variation among
  many, the canonical one.
- Invariants this must not break: deterministic output, append-only writes, the
  immutable mirror.

## Alternatives considered

- **Keep cheapest-first (vision only on image-only pages)** — rejected: it leaves
  born-digital pages with a single unverifiable reading and nothing to diff against,
  which defeats the QA purpose of the corpus.
- **Run a single "best" local model on born-digital pages** — rejected: which model
  is best is itself a thing the corpus is meant to reveal; picking one a priori
  hides the comparison the user asked for.
