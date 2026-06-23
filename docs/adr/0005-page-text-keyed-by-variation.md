# ADR-0005: Key `page_text` by a surrogate content-hash id so a page holds every variation

Status: Accepted
Date: 2026-06-22

## Context

`page_text` is keyed `PRIMARY KEY (page_id, rev)` — one transcription lineage per
page — and `export_exploded` takes the max-rev row per page. That encodes "one
reading per page," which is exactly what
`docs/problem-transcription-corpus.md` identifies as the problem: the text is
unverifiable because there is no second reading to compare against.

The corpus must instead hold **every variation** of a page: the exact PDF text
layer plus one reading per vision model. The natural identity of a variation is
`(page_id, source, model, rev)`. But `model` is null for the `pdf_text` source, and
DuckDB forbids nulls in `PRIMARY KEY` columns, so that tuple cannot be the key
directly. The table already carries `source` / `model` / `fidelity` columns — the
only thing missing is a key that admits many variations per page.

## Decision

Key `page_text` by a surrogate `id TEXT PRIMARY KEY` equal to a stable content hash
of `(page_id, source, model, rev)` (`pt_<sha16>`), leaving `model` nullable. This
matches the project's existing stable-content-hash id convention (`doc_<sha16>`),
enforces variation uniqueness without a null-in-key problem, and keeps `pdf_text`
honestly `model = null`. `SCHEMA_VERSION` → 10; per-case DBs are regenerable, so the
bump needs no in-place migration.

## Consequences

- A page holds N variations, each **individually addressable** by a stable id — the
  anchor point the future entity/relationship graph needs.
- Append-only is preserved per variation: re-inserting the same
  `(page_id, source, model, rev)` produces the same id and conflicts, so rev 0 of any
  variation stays immutable; a re-run appends the next rev *within that variation*.
- `export_exploded` changes from max-rev-per-page to latest-rev-per-`(page, source,
  model)`, returning a list of variations per page.
- Invariants this must not break: the mirror stays immutable, ids stay deterministic,
  writes stay append-only.

## Alternatives considered

- **Composite PK `(page_id, source, model, rev)`** — rejected: DuckDB disallows null
  PK columns, so `pdf_text` would need a `model` sentinel, making the stored data and
  the export less honest.
- **No primary key, uniqueness enforced only by the writer** — rejected: loses the
  database-level append-only guard that protects the immutable-record invariant.
