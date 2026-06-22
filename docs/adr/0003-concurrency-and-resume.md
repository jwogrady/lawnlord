# ADR-0003: Concurrency and idempotent resume for the transcribe run loop

Status: Proposed
Date: 2026-06-22

## Context

`transcribe_case` is a serial `for` loop over pages, each a blocking call, with
no resume: a re-run or crash recovery re-transcribes all pages and appends a
fresh `rev` to every one — full re-spend. Two run-loop properties are needed
independent of which backend (ADR-0001/0002) does the work: it must go fast, and
it must be safe to interrupt and resume.

The determinism invariant for the AI text layer is specifically about **insert
ordering and provenance**, not byte-identical model text (transcription is
non-deterministic by nature — see ADR-0001).

## Decision

- **Concurrency:** execute per-page calls through a bounded `ThreadPoolExecutor`
  (works uniformly for the sync cloud SDK and a local HTTP client). Worker count
  is configurable, with a sensible per-backend default (cloud bounded by rate
  limits; local bounded by GPU). Collect all results, then **insert in
  `ORDER BY page id`** so DB write order is deterministic regardless of
  completion order. Retry with backoff on transient errors (e.g. 429/529).
- **Idempotent resume:** by default, **skip pages that already have a revision**
  in `page_text` (`--force` re-transcribes and appends a new rev). An interrupted
  run resumes by re-running; completed pages are skipped.

## Consequences

- **Easier:** ~10–20× wall-clock on a full run; re-runs and crash recovery cost
  only the unfinished pages; experimentation (local-vs-cloud) becomes cheap to
  iterate.
- **Harder:** concurrent execution needs care that the `rev` computation and
  inserts remain race-free — resolved by computing results concurrently but
  **writing serially in page order** on one connection.
- **Invariants preserved:** append-only `page_text`; stable insert ordering;
  `generated_at` stamping; mirror never written.

## Alternatives considered

- **asyncio + async clients.** Higher ceiling, but the cloud SDK call and a
  local HTTP call are both fine under threads, and threads avoid restructuring
  the whole module async. Rejected for this scope.
- **Concurrent inserts (write as each page finishes).** Lower latency to first
  row, but non-deterministic insert order and `rev` races. Rejected — collect
  then ordered-write is simpler and deterministic.
- **A separate job/queue for resume state.** Over-built for a single case; the
  existing `page_text` rows *are* the resume state.
