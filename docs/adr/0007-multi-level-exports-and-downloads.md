# ADR-0007: Read-only exports and artifact downloads at every hierarchy level

Status: Accepted
Date: 2026-06-22

## Context

Today the case is read out through whole-case exports (`export-actual`,
`export-exploded`). `docs/problem-transcription-corpus.md` requires more: the QA
workflow and downstream analysis need to pull *any* slice of the fully-exploded
hierarchy — `case → filing → image → document → page` — in two forms: structured
**data** (for analysis and the eventual MCP surface) and the **artifacts**
themselves (the PDF, the page image, the text layer, each model's transcription —
the files a human keeps for the record). The confidence gauges also need aggregate
metrics, and those metrics must agree across the viewer, the exports, and any future
analysis consumer.

The viewer's standing invariant is that it never re-parses the intake and never
derives — it renders what the read-only exports give it.

## Decision

Provide read-only **structured exports addressable at each level** (`case → page`),
each a pure function of the DuckDB corpus, and **artifact downloads at each level**
(the level's files, or a bundle of them). Compute aggregate confidence metrics
(coverage, cross-model agreement, fidelity distribution, flag counts) in the
export/CLI layer — the DB-derived source of truth — not in the viewer; the viewer
only renders them.

## Consequences

- Any slice is independently auditable and feeds downstream analysis at the right
  granularity, without re-running the whole case.
- Metrics are computed once, server-side, so the viewer, the exports, and a future
  MCP consumer all report the same numbers — the viewer stays a pure renderer.
- More export/download surface to build and keep deterministic.
- Invariants this must not break: read-only, deterministic, the viewer never derives,
  the mirror is never mutated.

## Alternatives considered

- **Whole-case export only, slice and compute metrics client-side in the viewer** —
  rejected: it pushes derivation into the viewer (breaking the read-only-renderer
  invariant) and lets metrics drift between the viewer and any other consumer.
- **A separate metrics service/table materialized at build time** — deferred: the
  per-case DB is small and regenerable, so computing metrics on read is simpler and
  keeps them honest; revisit only if read-time cost becomes real.
