# Problem: transcription is slow, expensive, and ignores local compute

Status: Authoritative — the problem this effort solves. Ordered by impact.

## Problem

`lawnlord transcribe` is a serial, blocking loop: for a 255-page case it makes
255 sequential synchronous Claude-vision calls, one Opus request per page. The
result is ~15–25 minutes of mostly-idle wall-clock, full Opus cost on every page
regardless of how trivially legible it is, and **zero resume** — a re-run (or a
crash recovery) re-transcribes all 255 pages and appends a fresh revision to
each, paying the entire bill again.

It also sends every page to the cloud while a capable **local GPU sits idle**
(an RTX 3080, live in WSL2 via GPU paravirtualization). For a stack of clean,
printed court filings, that means paying a premium frontier model — and shipping
every page off-machine — to do work a local vision model could do for free.

This hurts on two axes at once: too slow to iterate, and more expensive than the
work requires. The current case (`odyssey-250914566`, 255 pages rendered,
`page_text` empty) has not been transcribed yet — so the cost of the first full
run, and every experiment after it, lands directly on this pain.

Worse, most of those calls are redundant. A measurement of this case found that
**149 of 255 pages are born-digital and carry a rich embedded text layer; 106 are
scanned/image-only** — the bulk of them inside two large filings (the 121-page
Motion for Summary Judgment, 94 image pages; the 64-page Answer, 8 image pages).
For a
born-digital page the PDF already contains the *exact* text — so the current
pipeline pays a frontier vision model to re-recognize pixels for text that is
already present, verbatim, in the file. That is both wasted spend and *worse*
output (OCR error introduced over ground truth). Re-OCR is genuinely required
only for the 106 image-only pages.

## Outcome

Transcription runs **local-first**: a local vision model on the RTX 3080
transcribes the bulk of pages for zero marginal cost and no rate limits,
**auto-escalating only the pages it can't read confidently** to cloud Claude
Opus. The result is fast (parallel against local VRAM, not an API quota), cheap
(cloud spend falls to a fraction of pages), more private (most pages never leave
the machine), safe to interrupt, and decided by **measured fidelity** rather
than assumption — all while the codebase's invariants stay intact.

A clarifying insight that de-risks this: transcription is **already
non-deterministic** (cloud Claude can vary run-to-run), which is exactly why
`page_text` is append-only — re-runs add a new `rev`, never overwrite. A local
model is therefore no less deterministic than today's cloud path; the
determinism invariant governs the mirror and the PNG renders, not the AI text
layer. "Run it locally" violates nothing.

## Success criteria

1. A full 255-page run completes in **single-digit minutes**, not ~20.
2. The **local tier handles the bulk** of pages; cloud Opus calls drop to a
   small, escalation-only fraction (driven by per-page `fidelity`).
3. A **measured** local-vs-Opus comparison exists on this case's pages (fidelity
   delta + the cloud-call fraction it implies), so the escalation threshold is a
   defensible number, not a guess.
4. Re-running transcribe **does not re-spend** on pages already transcribed; an
   interrupted run resumes without redoing completed pages.
5. Output stays **append-only and stably ordered**; the mirror is never written
   by transcribe; cloud stays opt-in (`ANTHROPIC_API_KEY`-gated, now only for
   escalation).
6. Born-digital pages are transcribed from the **embedded PDF text layer**
   (`source='pdf_text'`), not a model; only pages without usable embedded text
   reach the vision tier.

## Candidate levers, in order of impact

For `plan` to decompose — by expected payoff for *this single case*, not yet a
tech choice (specific local model/runtime is `plan`'s call). Lever **0** was
added after the born-digital measurement above; levers 1–5 keep their original
numbers so the milestone issues' cross-references stay valid.

0. **Extract the embedded PDF text layer first (free, deterministic ground
   truth).** For the 149 born-digital pages the PDF already holds the exact text;
   `pypdfium2` (already a dependency, used in `explode.py`) extracts it for free,
   deterministically, as ground truth — **not** OCR. A text-layer pre-pass writes
   those pages straight to `page_text` (`source='pdf_text'`, fidelity `1.0`) and
   hands only the image-only/thin pages to a vision tier. This trims the first
   full run from 255 model calls to ~106 *before* any local/cloud choice, and is
   strictly more accurate than re-recognizing pixels. It runs first, but the
   vision tier (levers 1–2) still carries ~106 pages — roughly *half* this case,
   not a handful — so it remains the load-bearing work, not an afterthought.
1. **Local vision tier as the default.** Run a local vision model on the GPU as
   the primary transcriber; cloud Opus becomes escalation-only. Attacks both
   axes at once — near-zero marginal cost and no rate limit (so it parallelizes
   freely) — and folds the old "concurrency" and "model tiering" levers into one
   structural change. Highest impact.
2. **Fidelity-gated cloud escalation.** Re-transcribe only low-`fidelity` pages
   on Opus. The `fidelity` self-estimate already in the schema is the gate; the
   threshold comes from the measurement in criterion 3. This is what keeps
   accuracy high while the local tier carries the volume.
3. **Idempotent skip / resume.** Skip pages that already have a revision
   (default on; explicit flag forces a true re-transcribe). Kills 100%
   re-spend, makes crash-resume free, and makes the local-vs-cloud experiments
   cheap to iterate.
4. **Transmitted-image right-sizing.** Feed the model an image at its optimal
   resolution without touching the stored deterministic PNG. Helps the local
   model's throughput and trims cloud-escalation tokens. Minor; do last.
5. **Batch API.** Likely unnecessary once the local tier lands — local is
   cheaper than batch's 50% discount and synchronous. Demoted to non-goal unless
   scope grows beyond one case.

## Prior art & reusable assets

- **RTX 3080, WSL2 (`/dev/dxg`, `nvidia-smi` visible)** — the idle asset this
  effort puts to work. Confirmed **10 GB total (~8.7 GB free** after the WSL
  display reservation), CUDA 13.2 / driver 595.97. That caps local model size:
  a 3B-class vision model fits comfortably; a 7B needs 4-bit quantization and a
  single-page-at-a-time image budget. `plan` picks the exact model/runtime.
- `src/lawnlord/transcribe.py` — current serial implementation. The **injectable
  client** seam (`messages.create`-shaped, already mocked in tests) is the hook
  for a pluggable local backend; `transcribe_page` is the reusable per-unit
  primitive.
- The structured-output schema already returns a `fidelity` 0–1 self-assessment
  per page — the built-in gate for lever 2 and the metric for criterion 3.
- `page_text` is append-only with per-page `rev` (rev 0 immutable); resume reads
  existing revs rather than fighting this. Append-only is also *why* a
  non-deterministic local model is safe here.
- 255 page PNGs already rendered deterministically at 150 DPI (1275×1651) under
  `extracted/pages/` — the measurement corpus exists today.
- **`pypdfium2` is already a dependency** (renders pages in `explode.py`) and
  exposes per-page text extraction (`get_textpage().get_text_range()`) — the
  text-layer pre-pass needs no new dependency.
- **Measured for this case (per page, `pypdfium2`, `<100` non-ws chars = thin):**
  149/255 pages born-digital, 106 scanned/image-only. No PDF is fully image-only.
  The image pages cluster in `doc-25856216` (Motion for Summary Judgment, 121 pp /
  94 image), `doc-25980946` (Answer, 64 pp / 8 image), and `doc-24775937` +
  `doc-24775944` (2 image each). These 106 pages need vision OCR.

## Constraints

- Python (uv), Anthropic SDK for the cloud tier (injectable client; tests mock
  it, no network in CI). Append-only `page_text`; never write the mirror from
  transcribe.
- Local inference must run under **WSL2 GPU paravirtualization** on the 3080 and
  fit its VRAM; a missing/oversized GPU must degrade gracefully (fall back to
  cloud), not crash.
- Determinism invariant still holds for the mirror + PNG renders; timestamps
  come from `generated_at`, not wall-clock; output ordering stays stable.
- Cloud stays opt-in and is now escalation-only.

## Non-goals

- Multi-case / corpus-scale orchestration or a job queue (scope is this case).
- Batch API path (superseded by local-first at this scope).
- Finer PDF-to-document splitting, or changing the DPI of the **stored** PNGs.
  (Note: extracting a PDF's *existing* embedded text layer is **in scope** as
  lever 0 — it is distinct from pixel-recognition OCR, which stays a non-goal as
  a *primary* path; OCR/vision is the fallback only for image-only pages.)
- Any change to the Actual/Exploded lenses or the web viewer.
