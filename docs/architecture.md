# Architecture (developer code summary)

> **Provable from the code.** Every claim here is verifiable by reading the cited modules under
> `src/lawnlord/`. If this doc and the code disagree, **the code wins** — fix the doc. Aspirational
> and future design is not here; it lives in the [ROADMAP](../ROADMAP.md).

> **Alpha rebuild.** The intake standard is the deterministic `rake` zip; DuckDB is built from it
> exclusively. The additive layer (analysis, AI, document explosion, reconstruction, providers, the
> web app) was removed — see the [CHANGELOG](../CHANGELOG.md). What remains is the foundation below;
> the zip → `CaseModel` reader and the two views are the next branches.

## Modules (`src/lawnlord/`)

| Module | Responsibility |
|---|---|
| `cli.py` | Register subcommands (`start` only), resolve a configurable intake root, dispatch, render Rich output |
| `intake.py` | Resolve intake/corpus layout from a root + optional `lawnlord.toml`; locate the intake zip; `scaffold` |
| `workspace.py` | The resolved `Case` (model + output paths). `from_intake` is a stub awaiting the zip reader |
| `models.py` | The `CaseModel` data contract (case/identity/parties/events/documents/…) + `case_slug`, `is_suspicious_entry`, `FILES_DIRNAME` |
| `db.py` | Open/create the per-case DuckDB; idempotent versioned schema |
| `ingest.py` | Insert docket metadata from a `CaseModel` (cases / parties / events / images / image_events / financials) |
| `hashing.py` | Content hashing (`sha256_*`) + the build timestamp |
| `console.py` | Shared Rich `console` singleton |
| `__main__.py` | `python -m lawnlord` → `cli.main()` |

## CLI

One subcommand registered in `cli.py`: `start` (scaffold an intake folder). See [`ux.md`](ux.md).

## Data flow

```
intake zip (rake: schema.json + data.json + files/ + pages/)
  └─ [next branch] reader → CaseModel        (models.CaseModel; replaces the removed providers)
       └─ ingest.ingest_case → DuckDB: cases, parties, events, images, image_events, financials
            └─ [next branches] Actual view + Exploded view read the index + files/
```

Today the reader is not yet wired (`workspace.Case.from_intake` raises `NotImplementedError`);
`ingest.ingest_case` is functional given a `CaseModel`.

## DuckDB schema (`db.py`, `SCHEMA_VERSION = 6`)

Tables: `schema_meta`, `cases`, `parties`, `financials`, `financial_transactions`, `case_gaps`,
`events`, `images`, `image_events`, plus inherited tables the current ingest no longer populates
(`documents`, `chunks`, `extracted_dates`, `knowledge_documents`) — to be **re-scoped to the zip's
level** in the rebuild. The DB is a derived, regenerable index — a pure function of the intake; it
never authors content.

## Enforced invariants

- **Deterministic & regenerable** — timestamps come from the caller's `generated_at` (never
  wall-clock); IDs are stable content hashes; output is ordered; re-ingesting identical inputs is
  byte-identical (`ingest.py`).
- **Derived index** — DuckDB is a pure function of the intake; the database never authors content.
- **Path-traversal safety** — `models.is_suspicious_entry` flags zip entries that would escape an
  extraction root (used when extracting the zip's `files/`).

## Not built yet (see the ROADMAP)

The zip → `CaseModel` reader, the Actual and Exploded views, and the re-scoped DuckDB schema are the
near-term work. Beyond them, there are **no** analysis/AI layers, no document explosion, no
reconstruction, no entity/relationship graph, and no computed timeline — that is the prerequisite
chain in the [ROADMAP](../ROADMAP.md). It is not in the code today, so it is not described here.
