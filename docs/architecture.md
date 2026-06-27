# Architecture (developer code summary)

> **Provable from the code.** Every claim here is verifiable by reading the cited modules under
> `src/lawnlord/` (Python pipeline) and `web/` (the viewer). If this doc and the code disagree, **the
> code wins** — fix the doc. Aspirational and future design is not here; it lives in the
> [ROADMAP](../ROADMAP.md).

The intake standard is the deterministic `rake` zip; the per-case DuckDB is built from it exclusively
and is a derived, regenerable index. On top of the DuckDB mirror sit additive layers — page explosion,
AI transcription, and spatial anchoring — and a local Bun/TypeScript viewer (`web/`) that reads the
case **only** through the Python CLI's read-only JSON exports.

## Modules (`src/lawnlord/`)

| Module | Responsibility |
|---|---|
| `cli.py` | Register the subcommands (see [`ux.md`](ux.md)), resolve a configurable intake root, dispatch to per-command handlers, render Rich output |
| `intake.py` | Resolve intake/corpus layout from a root + optional `lawnlord.toml`; `resolve_packet` locates the intake zip; `scaffold` writes the starter layout |
| `reader.py` | Extract the zip **safely** (path-traversal checked), **validate** `data.json` against the bundled `schema.json`, and map it to a `CaseModel` (values kept verbatim); `find_intake_dir`, `captured_at`, `manifest_declared_hashes` |
| `workspace.py` | The resolved `Case` (model + output paths). `from_intake` reads/validates the intake via `reader.load_case_model` |
| `models.py` | The `CaseModel` data contract (identity / parties / events / documents / financials) + `case_slug`, `is_suspicious_entry`, `FILES_DIRNAME` |
| `db.py` | Open/create the per-case DuckDB; the idempotent, versioned schema (`SCHEMA_VERSION = 12`); `load_fts` |
| `ingest.py` | Insert the docket mirror from a `CaseModel` (`cases` / `parties` / `events` / `images` / `image_events` / `financials` / `financial_transactions`); verify image bytes against `manifest.json` |
| `explode.py` | Render each filed PDF's pages to PNGs and populate the Exploded layer (`documents` + `pages`) |
| `transcribe.py` | AI transcription per page into `page_text` (PDF text layer + cloud Claude + local Ollama + llama.cpp tiers); fidelity-gated escalation; backend measurement |
| `regions.py` | Capture the spatial-anchor layer (`page_regions`): one normalized bounding box per text span, from PDF glyph geometry (ADR-0009) |
| `export.py` | Read-only case views out of the mirror: the Actual lens, the addressable Exploded lens, divergence/confidence metrics, and per-page regions |
| `logging_setup.py` | Per-run file logging under `case_dir/logs/` for the transcription pipeline (additive to the Rich console) |
| `hashing.py` | Content hashing (`sha256_*`) + the build timestamp |
| `console.py` | Shared Rich `console` singleton |
| `__main__.py` | `python -m lawnlord` → `cli.main()` |

## The viewer (`web/`)

A local, single-user Bun/TypeScript app — a lens switcher over the same immutable record. It reads the
case **only** through the Python CLI's read-only JSON exports (`uv run lawnlord export-actual` /
`export-exploded` / `export-metrics` / `export-regions`), never by re-parsing the zip, and serves the
filed PDFs, the captured Odyssey `pages/*.html`, and the page PNGs from disk. `index.ts` is the
`Bun.serve()` server (loopback-only by default); `app.ts` the front end; `download.ts` the multi-level
artifact downloads; `paths.ts` the path-confinement helper.

## CLI

Ten subcommands registered in `cli.py`'s `build_parser` / `COMMANDS` map: `start`, `import`,
`export-actual`, `export-exploded`, `export-metrics`, `export-regions`, `regions`, `explode`,
`transcribe`, `measure`. See [`ux.md`](ux.md) for each command's args, flags, and outputs.

## Data flow

```
intake zip (rake: schema.json + data.json + manifest.json + files/ + pages/)
  └─ reader.load_case_model → CaseModel        (validates data.json against schema.json)
       └─ ingest.ingest_case → DuckDB mirror: cases, parties, events, images,
       │                       image_events, financials, financial_transactions
       ├─ explode.explode_case → documents + pages (+ page PNGs under extracted/pages/)
       │    └─ transcribe.transcribe_case → page_text (PDF text layer + each vision model)
       │    └─ regions.capture_pdf_regions → page_regions (boxes per span; ADR-0009)
       └─ export.* (read-only) → Actual / Exploded / metrics / regions JSON
            └─ web/ viewer renders the lenses (shells to the CLI exports; serves files/PDFs/PNGs)
```

## Enforced invariants

- **Deterministic & regenerable** — timestamps come from the caller's `generated_at` (the zip's
  `manifest.json` `capturedAt`, never wall-clock); IDs are stable content hashes; output is ordered;
  re-running identical inputs is byte-identical. Per-case DBs are regenerable, so a `SCHEMA_VERSION`
  bump needs no in-place migration — `apply_schema` refuses a stamped-version mismatch and the operator
  re-imports.
- **Derived index** — DuckDB is a pure function of the intake; the database never authors content.
- **Additive layers never mutate the mirror** — explode, transcribe, and regions only *add* rows
  (`documents`/`pages`, `page_text`, `page_regions`) that reference the mirror; `page_text` is
  append-only per variation (a re-run appends a revision). A region with no reliable geometry is absent,
  never fabricated.
- **Path-traversal safety** — `models.is_suspicious_entry` flags zip entries that would escape the
  extraction root (used by `reader.extract_zip`); the viewer's `paths.safeJoin` confines served files.
- **Manifest verification** — `ingest` re-hashes each filed PDF and checks it against `manifest.json`,
  failing loud on a mismatch.
- **Single writer per case** — DuckDB allows at most one read-write process per case file at a time, and
  refuses a read-only open too while a writer holds the lock (so the viewer/query commands cannot read a
  case *during* an active `import`/`explode`/`transcribe`/`regions` run — see
  [ADR-0003](adr/0003-concurrency-and-resume.md)). All paths open through `db.open_case_db`, the single
  SQL open site, which turns DuckDB's raw lock `IOException` into a clear `CaseDatabaseBusy` error naming
  the case path and likely cause (another lawnlord process is writing it), distinct from a
  missing/corrupt file, and exits non-zero so a blocked run is never mistaken for a completed one. Run a
  case's write commands serially, and view/query it only after the write finishes.

## Not built yet (see the ROADMAP)

There is no analysis / entity-relationship graph, no computed timeline, and no accept/decline UI; the
viewer is read-only. Those are the near-term work in the [ROADMAP](../ROADMAP.md); they are not in the
code today, so they are not described here.
