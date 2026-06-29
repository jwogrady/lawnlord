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
# Python CLI (run via uv; console script is `lawnlord`). Python 3.13+; deps via uv (uv.lock).
uv run pytest                          # fast characterization suite (slow tests excluded by default)
uv run pytest -m slow                  # real-fixture acceptance tests (round-trip the 17 MB court export)
uv run pytest tests/test_export.py     # one file
uv run pytest tests/test_export.py::test_name -x   # one test, stop on first failure
uv run pytest --collect-only -q        # the last line is the authoritative test count
uv run mypy src/lawnlord               # type check (lenient baseline; ratchet UP, never loosen)
uv run ruff check                      # lint (src/, tests/, web/; scripts/cosmic is excluded)
uv run lawnlord <subcommand> ...       # invoke the CLI in-tree

# Web viewer (Bun, from web/ — use Bun, never Node/npm)
cd web && CASE_DIR=/path/to/case bun dev    # --hot reload; serves on PORT (default 4173)
cd web && bunx tsc --noEmit                 # typecheck
cd web && bun test                          # paths.test.ts
```

The checks that gate changes are `pytest`, `mypy`, `ruff`, and `tsc`.

### CLI subcommands (the real surface — see `cli.py`)

The full pipeline runs against a **case dir** (holds `lawnlord.duckdb`, `intake/<stem>/`, `extracted/`).
Pipeline order: `import → explode → transcribe → regions`, then the viewer reads via `export-*`.

```bash
lawnlord start [root]                   # scaffold intake/ + lawnlord.toml + intake README
lawnlord import <zip|dir> [--case-dir]  # extract zip safely, validate data.json vs schema.json, build DuckDB mirror
lawnlord explode [--case-dir] [--dpi 150]   # filed PDFs → documents + per-page PNGs (the Exploded layer)
lawnlord transcribe [--case-dir] [--backend all|cloud|local|llamacpp] [--model] [--force] \
                    [--workers N] [--ollama-host] [--llamacpp-host] [--max-image-px PX] \
                    [--escalate-below T] [--log-level LEVEL]
lawnlord regions [--case-dir]           # capture spatial-anchor boxes per text span from PDF geometry (deterministic)
lawnlord measure [--case-dir] [--models] [--cloud]   # compare vision backends on image-only pages (read-only)
lawnlord export-actual   [--case-dir]   # JSON: case + parties + register of actions (the Actual lens)
lawnlord export-exploded [--case-dir] [--filing|--image|--document|--page ID]  # JSON: images→docs→pages + every transcription
lawnlord export-metrics  [--case-dir] [--image ID]   # JSON: divergence/agreement/coverage rollups
lawnlord export-regions  [--case-dir] --page ID      # JSON: normalized boxes per text span for on-image highlight
```

`export-*` print **only JSON to stdout** (the viewer parses it) and open DuckDB read-only.
`transcribe` writes a per-run log under `<case-dir>/logs/`.

## Architecture

Data flow (each stage is idempotent and additive over the prior):

```
intake zip ─ import ─▶ DuckDB mirror ─ explode ─▶ documents + page PNGs ─ transcribe ─▶ page_text
                            │                                          regions ─▶ region boxes
                            └────────── export-actual / export-exploded / export-metrics / export-regions ──▶ JSON ──▶ web viewer
```

Module map (`src/lawnlord/`):

| Module | Responsibility |
|---|---|
| `cli.py` | argparse subcommands; the only place that wires modules together and renders Rich output |
| `reader.py` | zip → `CaseModel`: `extract_zip` (path-safe), `validate_data` (vs bundled schema), `load_case_model`, `captured_at` |
| `models.py` | the `CaseModel` data contract + pure helpers (`case_slug`, `is_suspicious_entry`, `FILES_DIRNAME`) |
| `intake.py` | the intake-folder contract (the deterministic zip) + `lawnlord start` scaffold + config resolution |
| `workspace.py` | the resolved `Case` (model + output paths); `Case.from_intake` |
| `db.py` | **the only SQL site.** Versioned, idempotent schema; `open_case_db`, `apply_schema`, optional FTS |
| `ingest.py` | `CaseModel` → mirror tables (cases, parties, events, images, image_events, financials, financial_transactions) |
| `explode.py` | render filed PDFs (pypdfium2) → `documents` + `pages` rows + PNGs under `extracted/pages/` |
| `transcribe.py` | PNG → AI transcription → append-only `page_text`; cloud (Claude), local (Ollama), llamacpp backends |
| `regions.py` | PDF text-span geometry → normalized bounding boxes (born-digital pages; deterministic) |
| `export.py` | read-only DuckDB → view JSON; divergence/agreement metrics computed here |
| `hashing.py` / `console.py` / `logging_setup.py` | content hashing + build timestamp; shared Rich `console`; per-run file logging |

### Key invariants (do not break these)

- **Derived, regenerable index.** DuckDB is a *pure function* of the intake zip; it never authors content.
  Per-case DBs are throwaway, so `SCHEMA_VERSION` bumps (`db.py`) need no migration — just re-import.
- **Deterministic output.** Timestamps come from the caller's `generated_at`/`captured_at` (never
  wall-clock); IDs are stable content hashes; insert order is fixed. Re-running on identical input is
  byte-identical. When adding writes, derive IDs by content hash and take time from the caller.
- **Mirror-then-add.** The seven mirror tables are the immutable base. `documents`, `pages`, `page_text`,
  and the region layer are additive layers that *reference* the mirror but never mutate it.
- **`page_text` is append-only per variation.** It is keyed by a surrogate content-hash `id` of
  `(page_id, source, model, rev)` so one page holds *every* reading — the PDF text layer plus one row
  per vision model. rev 0 of a variation is immutable; a re-run appends the next rev. Never overwrite.
- **Vision is opt-in.** `transcribe`/`measure` no-op (with a printed reason) unless `ANTHROPIC_API_KEY`
  is set or a local Ollama/llamacpp vision model is reachable. Tests inject a mock client — **never hit
  the network in CI.**
- **Path-traversal safety.** Zip extraction goes through `is_suspicious_entry`; preserve it.
- **Vocabulary:** an *image* = a filed PDF (the court's leaf); the *mirror* = the relational copy of `data.json`.

### Tests are characterization tests

The suite pins *current* behavior. A failing test is a behavior change to **approve by hand**, not to
silently update. If you intend a behavior change, update the test deliberately and say so.

### Per-machine backend wiring

The transcription pipeline is shared; only backend wiring differs per machine, isolated in gitignored
`.env` files seeded from committed `profiles/` (`cosmic-amd`, `cosmos-nvidia`, `cpu-fallback`). Activate
with `cp profiles/<name>.env .env` then append `ANTHROPIC_API_KEY`. The `llamacpp` backend (a standalone
GPU-mmproj llama.cpp server, ~10× faster at 300 DPI on the AMD/Vulkan workstation) is started via
`scripts/llamacpp_server.sh`. See `docs/reference/multi-machine-setup.md`.

### `web/` viewer

Has its own `web/CLAUDE.md` (Bun conventions). It reads the case **only** through the Python CLI's JSON
exports (`uv run lawnlord export-*`) and serves PDFs + captured `pages/*.html` + page PNGs — it never
re-parses the zip or touches DuckDB directly. Lenses: **Actual** (mirror), **Odyssey snapshot**
(verbatim captured HTML), **Exploded** (per-page comparison grid of every transcription variation).
Use Bun, not Node/npm.

## Docs as ground truth

The ADRs (`docs/adr/0001`–`0009`), `CHANGELOG.md`, `README.md`, `docs/architecture.md`, `docs/schema.md`,
and `docs/ux.md` track the current design. The **code remains ground truth**: `src/lawnlord/db.py`
(`SCHEMA_VERSION`) is authoritative for the schema — if you bump it, update `docs/schema.md` and
`docs/architecture.md` in the same change.
