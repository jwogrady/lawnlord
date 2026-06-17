# Architecture (developer code summary)

> **Provable from the code.** Every claim here is verifiable by reading the cited modules under
> `src/lawnlord/`. If this doc and the code disagree, **the code wins** — fix the doc. Aspirational
> and future design is not here; it lives in the [ROADMAP](../ROADMAP.md).

## Modules (`src/lawnlord/`)

| Module | Responsibility |
|---|---|
| `cli.py` | Register subcommands, parse flags, dispatch to handlers, render Rich output |
| `intake.py` | Resolve intake/corpus layout from a root + optional `lawnlord.toml`; `scaffold` |
| `workspace.py` | Resolve a `Case` from a provider intake folder; compute input/output paths |
| `providers.py` | Parse a provider intake (`ody`, `combo`) into a typed `CaseModel`; never mints IDs |
| `models.py` | Typed vocabulary: `SectionBoundary`, `PdfEntry`, `Party`, `Event`, `Attorney`, … |
| `archive.py` | Read-only inspection of the source packet; zip path-traversal safety |
| `boundaries.py` | Four-tier boundary detection (manual → bookmarks → heading scan → fallback); gapless 1..N coverage |
| `corpus.py` | Explode `archive → submission → document → section → page`; apply boundaries + curation |
| `curation.py` | Optional metadata overlay; enforce the `ALLOWED_CURATED_FIELDS` whitelist |
| `preservation.py` | Collect reviewed page analysis before `--force` and re-apply it after |
| `analysis_schema.py` | Empty page-analysis placeholders (never pre-filled); the shared JSON writer |
| `ocr.py` | Optional RapidOCR backend (lazy; CPU/GPU) for scanned pages |
| `db.py` | Open/create the per-case DuckDB; idempotent versioned schema; load FTS |
| `ingest.py` | Insert docket metadata (cases/parties/events/images/image_events/financials) |
| `index.py` | Insert corpus (documents/chunks) + page-coverage integrity guard + BM25 FTS build |
| `query.py` | Read-only queries: BM25 (LIKE fallback), needs-review, by phase/event/party |
| `unify.py` | Normalize a mirror-view model to the standard shape (ISO dates, source provenance) |
| `canonical.py` | Serialize/deserialize the standard `case.json` (`schemaVersion` `2.0`) |
| `pack.py` | `case.json` + `filings/` → one source-of-truth zip |
| `assemble.py` | Reassemble images → one master PDF in docket order; verify text/visual fidelity |
| `bundle.py` | The capstone: corpus + index + master PDF + pages + `case.json` → one zip |
| `reporting.py` | Human-readable archive report + boundary-template emit |
| `console.py` | Shared Rich `console` singleton |

## CLI

Nine subcommands registered in `cli.py`: `start`, `report`, `build`, `emit-boundaries`, `index`,
`pack`, `assemble`, `bundle`, `query`. See [`ux.md`](ux.md) for full per-command behavior.

## Data flow

```
provider intake (ody / combo)
  └─ providers.parse_*  → CaseModel
       ├─ corpus.write_corpus   → corpus/ (archive→submission→document→section→page artifacts)
       ├─ ingest.ingest_case    → DuckDB: cases, parties, events, images, image_events, financials…
       ├─ index.index_corpus    → DuckDB: documents, chunks (one row per page) + BM25 FTS
       ├─ assemble.assemble_case → case-master.pdf (+ .manifest.json), fidelity-verified
       ├─ canonical.to_canonical(unify(model)) → case.json (schemaVersion 2.0)
       ├─ pack.pack_case        → <case>.zip          (case.json + filings/)
       └─ bundle.bundle_case     → <case>.bundle.zip   (case.json + filings/ + master + pages/ + duckdb + manifest)
```

## DuckDB schema (`db.py`, `SCHEMA_VERSION = 3`)

Tables: `schema_meta`, `cases`, `parties`, `financials`, `financial_transactions`, `case_gaps`,
`events`, `images`, `image_events`, `documents`, `chunks` (one row per page; FTS over `text`), and
`knowledge_documents` (an unused stub). The DB is a derived, regenerable index — a pure function of
the intake + corpus; it never authors content. Columns are documented in
[`schema.md`](schema.md).

## Enforced invariants

- **Curation whitelist** — only `curation.ALLOWED_CURATED_FIELDS` may be overlaid; provenance,
  hashes, slugs, page ranges, tier/confidence, paths, and citations are always generated
  (`curation.py`).
- **Determinism / regenerable** — timestamps come from the caller's `generatedAt`; IDs are stable
  content hashes; output is ordered; re-index is byte-identical (`ingest.py`, `index.py`).
- **Integrity guard** — indexing fails and rolls back (writing nothing) unless pages cover exactly
  `1..N` and document page-sums match the actual page count (`index.py`).
- **Immutable provenance & empty legal stubs** — page-analysis legal fields are never pre-filled;
  `--force` re-applies only human-reviewed fields (`analysis_schema.py`, `preservation.py`).

## Not built yet (see the ROADMAP)

There are **no** entity/fact/claim tables, no relationships/case-graph, no
analysis/strategy/drafting layer, no computed timeline, and no AI agents; `knowledge_documents` is an
unused stub. That work is the prerequisite chain in the [ROADMAP](../ROADMAP.md) (v0.4.0–v0.8.0). It
is not in the code today — so it is not described here.
