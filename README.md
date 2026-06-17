# lawnlord

Turn a **legal court-record export** into a structured, citation-preserving, machine-readable case
dataset — and build toward a local-first engine that helps you *understand* a case, not just store
its files.

Every document is decomposed and traceable back to its original source page, so downstream legal
work (docket navigation, provenance, evidence mining, timeline reconstruction, filing generation)
rests on a trustworthy substrate. This is **not** a generic PDF splitter; it is legal-record
normalization.

> **Status (v0.1.0):** ships the deterministic **document exploder** described below — one PDF →
> Section → Page artifacts with full provenance. The case-workspace model, structured intake of
> court-portal exports (e.g. Odyssey), and the DuckDB index that ties together
> **case → event → document → section → page** are the active roadmap, not yet shipped. See
> [`docs/ROADMAP.md`](docs/ROADMAP.md) for the plan and [`CHANGELOG.md`](CHANGELOG.md) for what's
> released.

## What it does today (v0.1.0)

Given a source PDF (or a ZIP of court PDFs), lawnlord explodes each document into a five-level
corpus —

```
archive → submission → document → section → page
```

— writing section PDFs, per-page PDFs, extracted per-page text, per-page analysis stubs, section
metadata, a document `toc.json`, and a top-level `manifest.json`. Every page carries the citable
`sourcePageNumber` and a citation string, so nothing loses its provenance.

## Where it's going

The source of truth is an **intake folder organized by provider** (the first is `ody` = **Odyssey**,
`odyssey.mctx.org`): authoritative case/docket/document metadata (JSON) alongside the source PDFs.
The target model is **case → event → document → section → page**, with curated docket metadata
(parties, filing dates, document types, disposition) layered onto immutable documents and indexed in
a local DuckDB for query, analysis, and (eventually) drafting. Full plan:
[`docs/ROADMAP.md`](docs/ROADMAP.md); vision: [`docs/`](docs/).

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

`python -m lawnlord …` works as an alternative to the `lawnlord` console script. The corpus is
written to `dist/corpus/` by default (generated, gitignored).

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

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the phased plan — v0.1.0 (shipped) through the
case-workspace, Odyssey intake, and DuckDB-index milestone and beyond. The deeper vision (entity
graph, analysis, strategy, drafting) lives in [`docs/`](docs/).
