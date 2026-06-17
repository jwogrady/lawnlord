# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Documentation and project framing toward v0.2.0. Planned work — the case-workspace model, Odyssey
intake, and the DuckDB `case → event → document → section → page` index — is tracked in
[`docs/ROADMAP.md`](docs/ROADMAP.md).

### Added

- `docs/ROADMAP.md` — phased, issue-ready roadmap (v0.1.0 → Milestone 1 → later epics).
- `docs/plans/` — the v0.1.0 release record and the Milestone 1 design (case workspace + Odyssey
  intake + DuckDB index).

### Changed

- `pyproject.toml` metadata: refreshed description, added keywords, trove classifiers, and project
  URLs.

## [0.1.0] - 2026-06-16

First release: a standalone, deterministic legal court-record **exploder**.

### Added

- **Five-level corpus model** — explode one source ZIP of court PDFs into
  `archive → submission → document → section → page`, written under `dist/corpus/`
  (configurable with `--corpus-dir`).
- **Four-tier section-boundary detection** (`boundaries.py`), in priority order: manual
  curated boundaries (confidence 1.0) → PDF bookmarks/outline (0.95) → hardened legal-heading
  scan (0.65) → whole-PDF fallback (0.50). Every tier guarantees gapless 1..N page coverage;
  sections below confidence 0.9 are flagged `needsHumanReview`.
- **Per-page artifacts** — section PDFs, per-page PDFs, extracted per-page text, per-page
  analysis stubs, section `metadata.json`, document `toc.json`/`document-analysis.json`, and a
  top-level `manifest.json` and `archive.json`. Every page carries both its in-section page
  number and the citable `sourcePageNumber`, plus a citation string.
- **Curated-metadata overlay** (`corpus-curation.json`) restricted to a field whitelist;
  provenance, page ranges, hashes, slugs, boundary tier/confidence, paths, and citations are
  always generated and can never be overridden.
- **`--force` review preservation** — human-reviewed page analysis (`needsReview: false`) is
  indexed and re-applied onto regenerated stubs across rebuilds, via exact and
  same-document/source-page fallback keys.
- **`--dry-run`** read-only archive/PDF/section report (writes nothing).
- **`--emit-boundary-template`** to draft a reviewable manual-boundary file.
- **CLI** via the `lawnlord` console script and `python -m lawnlord`.
- **Path-traversal safety** — suspicious zip entries are flagged and never extracted by name.
- **Characterization test suite** pinning current behavior; the baseline test skips when no
  packet is present.

### Scope

v0.1.0 is the exploder only. The broader "legal understanding engine" described in
[`docs/`](docs/) — a case-workspace model, DuckDB index, entity/relationship graph, and
analysis/strategy/drafting layers — is the **target vision and roadmap**, not yet implemented.

[0.1.0]: https://github.com/jwogrady/lawnlord/releases/tag/v0.1.0
