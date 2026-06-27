# ADR-0001: Local-first transcription with cloud escalation

Status: Accepted
Date: 2026-06-22

## Context

`transcribe` (F4, #95) sends every page PNG to cloud Claude Opus, one synchronous
call per page. For a 255-page case that is slow, pays a frontier-model price on
trivially-legible pages, and ships every page off-machine — while a capable local
GPU (RTX 3080, 10 GB) sits idle. See `docs/problem-transcription-efficiency.md`.

The current code already has the right seam: `transcribe_page` takes an
**injectable client** shaped like the Anthropic SDK's `messages.create`, and the
structured output already returns a per-page `fidelity` (0–1) self-assessment.

A determinism concern could block "run it locally": local model output is not
byte-reproducible. But transcription is *already* non-deterministic — cloud
Claude varies run-to-run — which is exactly why `page_text` is **append-only**
(re-runs add a new `rev`, never overwrite). The determinism invariant binds the
mirror and the PNG renders, not the AI text layer. So a local backend violates
nothing.

## Decision

Make transcription **local-first with cloud escalation**, behind a small backend
abstraction:

- Generalize the injectable seam into a `Transcriber` protocol:
  `transcribe_page(png_path) -> {text, fidelity, model}`.
- Two backends implement it: a **local** GPU backend (default) and the existing
  **cloud** Anthropic backend (now escalation-only).
- Policy: transcribe every page locally; **auto-escalate pages whose `fidelity`
  falls below a measured threshold** to cloud Opus, appending the cloud result as
  a new `rev` (append-only preserved — the local attempt stays as its own rev).
- Cloud stays opt-in (`ANTHROPIC_API_KEY`); the local tier degrades gracefully to
  cloud when no GPU is available, rather than crashing.

## Consequences

- **Easier:** cost drops to an escalation-only fraction of pages; the local tier
  parallelizes freely (no API rate limit); most pages never leave the machine.
- **Harder:** a new local-inference dependency and its runtime (see ADR-0002);
  two backends to test; an escalation threshold that must be *measured*, not
  guessed (the measurement is a planned issue under this milestone).
- **Invariants preserved:** `page_text` stays append-only; the mirror is never
  written by transcribe; output stays stably ordered; `generated_at` (not
  wall-clock) still stamps every row.

## Alternatives considered

- **Keep cloud-only, just add concurrency + cheaper cloud model.** Faster and a
  bit cheaper, but leaves the GPU idle and still pays per page. Concurrency is
  still adopted (ADR-0003) — but on its own it does not address cost or privacy.
- **Local-only (no cloud at all).** Maximally private and free, but accepts the
  local model's accuracy ceiling on hard pages with no recourse. Rejected:
  legal records need a high-accuracy fallback. Escalation gives both.
- **Cloud Batch API (50% off, async).** Cheaper than per-page cloud, but still
  off-machine and still paid; local-first beats it at single-case scope. Left as
  a non-goal.
