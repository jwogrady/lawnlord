# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

lawnlord is a local-first legal **case-understanding engine**. Its single source of truth is the
**deterministic intake zip** produced by `jwogrady/rake` (`schema.json` + `data.json` + `manifest.json`
+ `files/` + `pages/`), self-verifying via per-file sha256. lawnlord builds a per-case DuckDB index
**from that zip exclusively** and layers views and AI transcription on top.

Governing principle, enforced throughout: **mirror the court's record exactly as the immutable base,
then everything else is additive.** No analysis, transcription, or overlay may ever alter the mirrored
record or its provenance. Legal conclusions are human-owned; the tool surfaces and proposes only.

Two engines: a **Python CLI** (`src/lawnlord/`) that does all ingest/DuckDB/AI work, and a **Bun/TypeScript
web viewer** (`web/`) that only *reads* the case via the CLI's JSON exports and serves the filed PDFs.

## Commands

```bash
# Python CLI (run via uv; console script is `lawnlord`)
uv run pytest                          # full characterization suite
uv run pytest tests/test_export.py     # one file
uv run pytest tests/test_export.py::test_name -x   # one test, stop on first failure
uv run lawnlord <subcommand> ...       # invoke the CLI in-tree

# Web viewer (Bun, from web/)
cd web && CASE_DIR=/path/to/case bun dev    # --hot reload; serves on PORT (default 4173)
cd web && bunx tsc --noEmit                 # typecheck
```

There is no Python linter/formatter configured and no JS test/lint runner wired in `web/package.json`
— `pytest` and `tsc` are the checks. Python requires **3.13+**; deps are managed by `uv` (`uv.lock`).

### CLI subcommands (the real surface — see `cli.py`)

The full pipeline runs against a **case dir** (holds `lawnlord.duckdb`, `intake/<stem>/`, `extracted/`):

```bash
lawnlord start [root]                   # scaffold intake/ + lawnlord.toml
lawnlord import <zip|dir> [--case-dir]  # extract zip safely, validate data.json vs schema.json, build DuckDB mirror
lawnlord explode [--case-dir] [--dpi]   # filed PDFs → documents + per-page PNGs (the Exploded layer)
lawnlord transcribe [--case-dir] [--backend all|cloud|local] [--model] [--force] [--workers] [--escalate-below T]
lawnlord measure [--case-dir] [--models] [--cloud] [--sample]   # compare vision backends (read-only)
lawnlord export-actual   [--case-dir]   # JSON: case + parties + register of actions
lawnlord export-exploded [--case-dir] [--filing|--image|--document|--page ID]  # JSON: images→docs→pages + every transcription
lawnlord export-metrics  [--case-dir] [--image ID]   # JSON: divergence/agreement/coverage rollups
```

`export-*` print **only JSON to stdout** (the viewer parses it) and open DuckDB read-only.

## Architecture

Data flow (each stage is idempotent and additive over the prior):

```
intake zip ─ import ─▶ DuckDB mirror ─ explode ─▶ documents + page PNGs ─ transcribe ─▶ page_text
                            │                                                                │
                            └────────────────── export-actual / export-exploded / export-metrics ──▶ JSON ──▶ web viewer
```

Module map (`src/lawnlord/`):

| Module | Responsibility |
|---|---|
| `cli.py` | argparse subcommands; the only place that wires modules together and renders Rich output |
| `reader.py` | zip → `CaseModel`: `extract_zip` (path-safe), `validate_data` (vs bundled schema), `load_case_model`, `captured_at` |
| `models.py` | the `CaseModel` data contract + pure helpers (`case_slug`, `is_suspicious_entry`, `FILES_DIRNAME`) |
| `workspace.py` | the resolved `Case` (model + output paths); `Case.from_intake` |
| `db.py` | **the only SQL site.** Versioned, idempotent schema; `open_case_db`, `apply_schema`, optional FTS |
| `ingest.py` | `CaseModel` → mirror tables (cases, parties, events, images, image_events, financials, financial_transactions) |
| `explode.py` | render filed PDFs (pypdfium2) → `documents` + `pages` rows + PNGs under `extracted/pages/` |
| `transcribe.py` | PNG → AI transcription → append-only `page_text`; cloud (Claude) + local (Ollama) backends |
| `export.py` | read-only DuckDB → view JSON; divergence/agreement metrics computed here |
| `hashing.py` / `console.py` | content hashing + build timestamp; shared Rich `console` singleton |

### Key invariants (do not break these)

- **Derived, regenerable index.** DuckDB is a *pure function* of the intake zip; it never authors content.
  Per-case DBs are throwaway, so `SCHEMA_VERSION` bumps need no migration — just re-import.
- **Deterministic output.** Timestamps come from the caller's `generated_at`/`captured_at` (never
  wall-clock); IDs are stable content hashes; insert order is fixed. Re-running on identical input is
  byte-identical. When adding writes, derive IDs by content hash and take time from the caller.
- **Mirror-then-add.** The seven mirror tables are the immutable base. `documents`, `pages`, `page_text`
  are additive layers that *reference* the mirror but never mutate it.
- **`page_text` is append-only per variation.** It is keyed by a surrogate content-hash `id` of
  `(page_id, source, model, rev)` so one page holds *every* reading — the PDF text layer plus one row
  per vision model. rev 0 of a variation is immutable; a re-run appends the next rev. Never overwrite.
- **Vision is cloud opt-in.** `transcribe`/`measure` no-op (with a printed reason) unless `ANTHROPIC_API_KEY`
  is set or a local Ollama vision model is installed. Tests inject a mock client — **never hit the network in CI.**
- **Path-traversal safety.** Zip extraction goes through `is_suspicious_entry`; preserve it.
- **Vocabulary:** an *image* = a filed PDF (the court's leaf); the *mirror* = the relational copy of `data.json`.

### Tests are characterization tests

The suite pins *current* behavior. A failing test is a behavior change to **approve by hand**, not to
silently update. If you intend a behavior change, update the test deliberately and say so.

### `web/` viewer

Has its own `web/CLAUDE.md` (Bun conventions). It reads the case **only** through the Python CLI's JSON
exports (`uv run lawnlord export-*`) and serves PDFs + captured `pages/*.html` — it never re-parses the
zip or touches DuckDB directly. Use Bun, not Node/npm.

## Docs caveat

The ADRs (`docs/adr/0001`–`0009`) and `CHANGELOG.md` track the current design. But `README.md` and
`docs/architecture.md` lag the code — they describe an earlier "alpha rebuild" where `import` and the
reader weren't wired and the schema was v6. **The code is the ground truth** (schema is v11; the full
import→explode→transcribe→export pipeline exists). If you touch those docs, reconcile them to the code.
