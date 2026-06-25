# Project Mapper

**Date:** 2026-06-25
**Reviewer:** jwogrady

## Finding

`lawnlord` is a single-project, local-first **legal case-understanding engine** (not a monorepo). Its governing invariant is *mirror the court's deterministic intake zip exactly as an immutable base, then everything else is additive.* The codebase is two cooperating runtimes in one repo: a **Python CLI** (`src/lawnlord/`, ~3,601 LOC) that owns all data — it ingests the intake zip into a per-case DuckDB index and exposes read-only JSON exports — and a **Bun/TypeScript web viewer** (`web/`, ~2,094 LOC) that is a pure read-only window, shelling out to the CLI (`uv run lawnlord export-*`) for every piece of dynamic data and never touching the DB or zip directly. The structure is clean and legible: 15 Python modules with single responsibilities, a flat public API re-exported from `__init__.py`, and a versioned (v11) idempotent DuckDB schema.

The project is at **version 0.4.0**, self-described as "alpha — mid-rebuild," re-founded on a zip standard produced by a sibling tool (`jwogrady/rake`). Two lenses are implemented (**Actual** = Odyssey-faithful register + native PDFs; **Exploded** = per-page QA comparison grid across transcription variants). The roadmap sequences everything else (cross-referencing, analysis lenses, corpus-as-MCP) on top of this substrate.

Tooling is minimal: Python 3.13+ managed by `uv` with `hatchling` build backend; tests via `pytest` (27 passing, characterization-style); the web app uses Bun native (`Bun.serve()`, no framework, no bundler). Notably **no linter/formatter/type-checker is installed or configured** (`ruff`, `mypy` absent despite cache dirs being gitignored), and **no CI** (`.github/workflows/` does not exist).

## Evidence

- **Project type/purpose:** `pyproject.toml` `name = "lawnlord"`, `version = "0.4.0"`, `requires-python = ">=3.13"`; `README.md` lines 1–40; entry point `[project.scripts] lawnlord = "lawnlord.cli:main"`.
- **Python source (15 modules, 3,601 LOC):** `transcribe.py` (775) · `export.py` (609) · `cli.py` (583) · `db.py` (255) · `reader.py` (240) · `models.py` (231) · `regions.py` (207) · `ingest.py` (197) · `intake.py` (147) · `workspace.py` (126) · `explode.py` (109) · `__init__.py` (84) · `hashing.py` (23) · `console.py` (9) · `__main__.py` (6).
- **Entry points:** CLI `src/lawnlord/cli.py:main` (≈321–329) → `build_parser()` (≈80–246); subcommands: `start`, `import`, `export-actual`, `export-exploded`, `export-metrics`, `export-regions`, `regions`, `explode`, `transcribe`, `measure`. `python -m lawnlord` via `__main__.py`.
- **DuckDB schema:** `src/lawnlord/db.py` `SCHEMA_VERSION = 11` (line 48); 12 tables (`schema_meta`, `cases`, `parties`, `financials`, `financial_transactions`, `events`, `images`, `image_events`, `documents`, `pages`, `page_text`, `page_regions`); `apply_schema()` idempotent (≈231–237).
- **Transcription backends:** `src/lawnlord/transcribe.py` — `CloudTranscriber` (Anthropic, default `claude-opus-4-8`), `LocalTranscriber` (Ollama, default `qwen2.5vl:7b`, host `:11434`), `LlamaCppTranscriber` (GPU, host `:18082`); dynamic model discovery `installed_vision_models()` (≈386–399).
- **Web app (~2,094 LOC):** `web/index.ts` (151) routes `/api/case`, `/api/exploded`, `/api/metrics`, `/api/regions`, `/download/*`, `/files/*`, `/pages/*`, `/png/*`; port `4173` (index.ts:20); shells via `Bun.$` `.cwd(REPO_ROOT)`. `web/app.ts` (828) UI; `web/download.ts` (417) multi-level bundler with `safeJoin` path-traversal guard.
- **Dependencies (top):** `anthropic>=0.69`, `duckdb>=1.1`, `jsonschema>=4.0`, `pillow>=10.0`, `python-dotenv>=1.0`, `pypdfium2>=4.30`, `python-slugify>=8.0.4`, `rich>=15.0.0`. Dev: `pytest>=8.0`, `pypdf>=4.0`.
- **Tests (11 files, ~2,068 LOC):** `test_transcribe.py` (681), `test_metrics.py` (295), `test_explode.py` (266), `test_regions.py` (237), `test_reader.py` (219), `test_intake.py` (110), `test_helpers.py` (81), `test_export.py` (78), `test_intake_root.py` (45), `test_db.py` (41), `conftest.py` (15). `pytest 9.1.0` installed.
- **Tooling gaps:** `uv run ruff --version` → not available; `uv run mypy --version` → not available; no `.github/workflows/`; no `[tool.ruff]`/`[tool.mypy]` in `pyproject.toml`.
- **ADRs:** `docs/adr/0000`–`0009`; 0004–0009 Accepted, 0001–0003 Proposed.
- **Secrets:** `.env` exists and is gitignored; `.env.example` committed as template.

## Scoring

**Dimension:** Clarity of structure

**Score:** 8

**Rationale:** Module boundaries are crisp, the CLI/web split enforces the mirror-immutable invariant at the architecture level, and IDs are content-derived for determinism. Points off because the project is mid-rebuild (some inherited schema/doc drift) and lacks the basic hygiene scaffolding — linter, type-checker, CI — that a structure this clean otherwise deserves.

## Notes to Next Agent

- **Single project, two runtimes** (Python CLI is the data authority; Bun web is read-only). Treat them as one system with a hard CLI boundary.
- **Mirror-immutable / layers-additive is THE invariant.** Every downstream dimension should test whether code honors it (canonical vs. derived vs. analysis layers must never bleed). This is the project's stated north star and the natural Agent 07 custom focus.
- **No linter/type-checker/CI** — flag for Code Quality (03) and Product Readiness (06).
- **27 tests are characterization-only**, mocked vision models, no acceptance test against the real case — flag for Testing (04).
- Docs are strong at the top (README/CHANGELOG/ROADMAP/ADRs 0007–0009) but `schema.md` is a stub and `export-*` CLI lacks a formal spec — flag for Documentation (01).
- **Critical:** The whole value proposition is *provenance you can trust*. The audit should weight data-integrity and layer-separation findings heavily.
