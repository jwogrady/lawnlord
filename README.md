# lawnlord

Turn a downloaded **legal court-record packet** (one ZIP of court PDFs) into a structured,
citation-preserving, machine-readable case dataset — a five-level model:

```
archive → submission → document → section → page
```

Every unit is traceable back to its original source PDF page, so downstream legal work
(docket navigation, provenance, evidence mining, timeline reconstruction, filing generation)
is built on a trustworthy substrate. This is **not** a generic PDF splitter; it is
legal-record normalization.

> **Status (v0.1.0):** ships the deterministic exploder described below and nothing more.
> The CLI exposes the original flag interface; the `lawnlord start` intake-scaffold model,
> input-path decoupling, and the broader "legal understanding engine" (DuckDB index, entity
> graph, analysis/strategy/drafting) live in [`docs/`](docs/) as the **target vision/roadmap**,
> not current functionality. See [`CHANGELOG.md`](CHANGELOG.md) for what's in this release.
> The baseline test skips when no packet is present.

## Install

```bash
uv add lawnlord                      # as a project dependency
# or, for local/parallel development from a sibling checkout:
#   [tool.uv.sources] lawnlord = { path = "../lawnlord", editable = true }
```

## Usage

```bash
lawnlord --dry-run                   # read-only archive/PDF/section report; writes nothing
lawnlord                             # build the corpus (skips existing submissions)
lawnlord --force                     # full rebuild (preserves reviewed page analysis)
lawnlord --corpus-dir <dir>          # write the corpus elsewhere
lawnlord <path-to-zip>               # explicit archive instead of the default search
lawnlord --emit-boundary-template    # write a reviewable manual-boundary draft; writes nothing else
```

`python -m lawnlord …` works as an alternative to the `lawnlord` console script.

When no ZIP path is given, lawnlord searches known locations (`src/filings/E222C7C4.zip`, then
cwd-relative fallbacks). The corpus is written to `dist/corpus/` by default (generated,
gitignored).

## Architecture

Logic lives in the `lawnlord` package (`src/lawnlord/`); each module owns one concern, and
`__init__.py` re-exports the public API as a flat surface (`import lawnlord`).

| Module | Owns |
| --- | --- |
| `cli.py` | argparse + run dispatch (`--dry-run` / `--emit-boundary-template` / build) |
| `paths.py` | repo/intake layout, zip resolution, input filenames |
| `hashing.py` | `sha256_bytes` / `sha256_file` / `now_iso` primitives |
| `models.py` | `SectionBoundary`, `PdfEntry`, `unique_slug` |
| `boundaries.py` | four-tier section detection, heading helpers, `section_summary` |
| `curation.py` | curated-metadata overlay + allowed-field whitelist |
| `preservation.py` | `--force` reviewed-analysis collection + re-application |
| `analysis_schema.py` | page-analysis placeholders + `write_json` |
| `archive.py` | `inspect_archive` + zip-entry path-traversal safety |
| `corpus.py` | `explode_document`, `write_corpus`, manifest builders |
| `reporting.py` | `--dry-run` report + boundary-template emit |
| `console.py` | shared Rich `console` singleton |

## Detection tiers

Section boundaries are metadata-only proposals (1-based source-PDF page ranges always covering
pages 1..N with no gaps/overlaps), in priority order:

1. **Manual** — curated boundaries file. Always wins, confidence 1.0.
2. **Bookmarks** — top-level PDF outline entries, confidence 0.95 (pre-first-bookmark pages
   become a 0.60 front-matter section; filename-looking titles downgraded to 0.60).
3. **Heading scan** — hardened legal-heading detection, confidence 0.65.
4. **Fallback** — whole PDF as one section, confidence 0.50.

Sections below confidence 0.9 are flagged `needsHumanReview`.

## Guardrails

Page-analysis stubs hold only empty legal-review placeholders with `needsReview: true` — never
pre-filled. Legal conclusions are human work. Provenance, page ranges, hashes, slugs, boundary
tier/confidence, paths, and citations are always generated and can never be overridden by a
curation overlay.

## Development

```bash
uv run pytest                        # characterization suite (62 tests; baseline skips without a packet)
```

The tests are **characterization tests**: they pin current behavior, so a failing test is a
behavior change to approve by hand, not to silently update.

## Roadmap

The full target vision is documented in [`docs/`](docs/) — a local-first "legal understanding
engine." It is **not** implemented in v0.1.0. Near-term direction:

- `lawnlord start` — scaffold an intake folder a consumer project drops its packet into.
- Decouple input resolution from the fixed repo layout (operate on the intake folder / CLI args
  instead of a hardcoded `src/filings`).
- Subcommand CLI (`start`, `build`, `report`, …) replacing the current flags.
- A DuckDB index over the corpus, then entities, relationships, analysis, and drafting layers
  (see [`docs/architecture.md`](docs/architecture.md)).
