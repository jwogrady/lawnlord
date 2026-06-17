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

> **Status:** standalone, installable tool with an intake-folder workflow. Inputs and output
> are resolved from an intake the consumer project supplies — not a hardcoded layout.

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

lawnlord operates on an **intake folder** — a directory holding the source packet ZIP plus
optional curated inputs, with generated output written alongside. `lawnlord start` scaffolds it.

```bash
lawnlord start [root]                # scaffold intake/ + lawnlord.toml + an intake README
# ... drop the packet ZIP into the intake dir ...
lawnlord report [root]               # read-only archive/section report; never writes
lawnlord build [root]                # build the corpus from the intake packet
lawnlord build [root] --force        # rebuild existing submissions (preserves reviewed analysis)
lawnlord emit-boundaries [root]      # write a reviewable manual-boundary draft into the intake dir
```

`root` defaults to the current directory. `build`/`report`/`emit-boundaries` take `--packet` to
point at a specific ZIP. `python -m lawnlord …` works as an alternative to the console script.

### Intake layout

```text
<root>/
  lawnlord.toml      # optional config: intake/corpus dir names (defaults below)
  intake/            # inputs: the packet ZIP + optional curated files
    <packet>.zip
    bundle-boundaries.json   (optional — manual section boundaries, Tier 1)
    corpus-curation.json     (optional — curated metadata overlay)
  corpus/            # generated output (regenerable)
```

`lawnlord.toml` can remap these so a project with an existing layout adopts lawnlord without
moving files:

```toml
[lawnlord]
intake = "src/filings"
corpus = "dist/corpus"
```

## Architecture

Logic lives in the `lawnlord` package (`src/lawnlord/`); each module owns one concern, and
`__init__.py` re-exports the public API as a flat surface (`import lawnlord`).

| Module | Owns |
| --- | --- |
| `cli.py` | subcommands (`start` / `report` / `build` / `emit-boundaries`) + dispatch |
| `intake.py` | intake-folder contract: config (`lawnlord.toml`), packet resolution, `scaffold` |
| `hashing.py` | `sha256_bytes` / `sha256_file` / `now_iso` primitives |
| `models.py` | `SectionBoundary`, `PdfEntry`, `unique_slug` |
| `boundaries.py` | four-tier section detection, heading helpers, `section_summary` |
| `curation.py` | curated-metadata overlay + allowed-field whitelist |
| `preservation.py` | `--force` reviewed-analysis collection + re-application |
| `analysis_schema.py` | page-analysis placeholders + `write_json` |
| `archive.py` | `inspect_archive` + zip-entry path-traversal safety |
| `corpus.py` | `explode_document`, `write_corpus`, manifest builders |
| `reporting.py` | archive report + boundary-template emit |
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
uv run pytest                        # characterization + end-to-end suite (69 tests)
```

The tests are **characterization tests**: they pin current behavior, so a failing test is a
behavior change to approve by hand, not to silently update. `test_end_to_end.py` builds a tiny
corpus from synthetic PDFs and freezes the structural invariants (full page coverage, citation
model, unfilled page-analysis stub) that must hold for any input.

## Roadmap

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the phased plan — v0.1.0 (shipped) through the
case-workspace, Odyssey intake, and DuckDB-index milestone and beyond. The deeper vision (entity
graph, analysis, strategy, drafting) lives in [`docs/`](docs/).
