# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This changelog is the documented state **after** each release — what shipped. Planned work (the
state *before* a release) lives in the [ROADMAP](docs/ROADMAP.md); the current working state is
always the commit. Each release below links to its **release milestone** and the **issues** it
closed.

## [0.3.0] - 2026-06-17

**Milestone:** [v0.3.0 (#1)](https://github.com/jwogrady/lawnlord/milestone/1) · **Tag:** [v0.3.0](https://github.com/jwogrady/lawnlord/releases/tag/v0.3.0) _(GitHub release pending)_ · **Issues:** [#14](https://github.com/jwogrady/lawnlord/issues/14) · [#15](https://github.com/jwogrady/lawnlord/issues/15) · [#16](https://github.com/jwogrady/lawnlord/issues/16) · [#17](https://github.com/jwogrady/lawnlord/issues/17) · [#18](https://github.com/jwogrady/lawnlord/issues/18) · [#19](https://github.com/jwogrady/lawnlord/issues/19) · [#20](https://github.com/jwogrady/lawnlord/issues/20)

### Added

- **`lawnlord bundle` — the capstone (final output).** Wrap a complete case into one
  self-contained, cross-linked zip: `case.json` (the standard metadata wrapper, from
  `to_canonical(unify(model))`) + `filings/` (preserved original PDFs, hash-pinned — what
  `case.json`'s `file` paths point to) + `case-master.pdf` (the whole case reassembled in docket
  order, lossless) + `pages/<stem>/pNNN.txt` (per-page searchable text) + `lawnlord.duckdb` (the
  queryable index) + `bundle-manifest.json` cross-linking every image ↔ its pages ↔ its master-PDF
  page range ↔ its filing. Reading only `case.json` reaches every image; the lossless proof
  (text + visual) rides inside the bundle; every entry is a relative path (no escapes) and the
  bundle is regenerable from the intake. Real `combo`: 22 images + 255 searchable pages + 255-page
  master, text- and visual-lossless. This completes the v0.3.0 milestone (foundation + standard
  schema + DuckDB + capstone).

- **F4 — re-level the index to the source-true `Image → Document` vocabulary.** The DuckDB index
  now distinguishes an **image** (a filed PDF — Odyssey's own term) from the **documents within it**
  (Motion, Exhibit A, Affidavit…). Tables re-leveled: `documents` → `images`, `document_events` →
  `image_events`, and the old `sections` table → `documents` (the logical documents within an
  image); `chunks` now carry both `image_id` and `document_id`. Query API renamed to match
  (`images_by_phase/_event/_party`, `needs_review_documents`). Against the real `combo` case: 22
  images → 37 documents → 255 pages; the 121-page MSJ image explodes into its 9 bookmarked documents
  (Motion + Exhibits A–D + Affidavit), each a contiguous page range, junk bookmarks excluded. The
  exploder's on-disk corpus keeps its "section" vocabulary; it is mapped to `documents` at the index
  boundary. `SCHEMA_VERSION` → 2 (per-case DBs are regenerable; no migration). Design:
  `docs/plans/v0.3.0-complete-truth-and-full-text.md`.

- **`lawnlord assemble` — the lossless explode ↔ reassemble proof.** Reassemble a case's images
  back into one master PDF from the **preserved original images** (immutable, hash-pinned), in
  docket order, under a `FILING → IMAGE → DOC` outline (documents from each image's bookmarks, junk
  references filtered), carrying embedded file attachments across. Writes a `*.manifest.json`
  page→provenance sidecar and verifies page-for-page text fidelity, so "no context lost" is a
  checked invariant, not a claim. Against the real `combo` case: 22 images → one 255-page master,
  text-lossless, 61-entry outline, every page traceable to (image, source page). Design:
  `docs/plans/v0.3.0-complete-truth-and-full-text.md`.

- **Canonical case standard (`case.json`) + `lawnlord pack`.** Define the portable, versioned
  representation a provider adapter populates: `to_canonical(model)` / `from_canonical(dict)`
  round-trip a case losslessly through `case.json` (`SCHEMA_VERSION` 1.0). `lawnlord pack
  <intake> [-o <zip>]` produces the shippable **source of truth** — one self-contained zip with
  `case.json` (all the data) plus `filings/` (all the PDFs), where each document's `file` path is
  the same path it sits at in the zip. Missing source PDFs are reported, not silently dropped.
- **`combo` provider — cross-source merge.** Register the reconciled best-of-both intake (the
  recommended source of truth) as a first-class provider with its own `parse_combo` adapter. It
  takes the Odyssey export as the base (identity, parties, phase-tagged events, file-linked
  documents) and merges the re:SearchTX `meta.json`: attorney **bar numbers** onto parties, a
  **hearings** table (with results, e.g. the canceled bench trial), the **financial** summary
  (assessment / payments / balance), and a richer **docket** (the registrar/judge's free-text
  comments + per-document page counts) whose document names are linked back to the source PDFs.
  New model types: `Hearing`, `Financials`, `DocketEntry`, `DocketDocument`, and `Attorney.number`.
  Degrades to plain Odyssey parsing when no `meta.json` is present.

## [0.2.0] - 2026-06-16

**Release:** [v0.2.0](https://github.com/jwogrady/lawnlord/releases/tag/v0.2.0) · **Milestone:** none _(pre-milestone)_ · **Issues:** _pre-issue-tracking_

The case-understanding milestone: lawnlord now ingests a provider intake folder, indexes the whole
`case → event → document → section → page` model into DuckDB, queries it with provenance, and
optionally OCRs scanned pages.

### Added

- **Case workspace + Odyssey adapter** — `Case.from_intake()` resolves a case from a provider
  folder (`intake/<provider>/`); the `odyssey` adapter parses the case-summary / case-history /
  register-of-actions / filings JSON into typed identity, parties, phase-ordered events, and
  documents. No `REPO_ROOT` coupling.
- **DuckDB index** (`db.py`) — idempotent, versioned schema for
  `cases / parties / events / documents / document_events / sections / chunks`.
- **Docket ingest** (`ingest.py`) — `ingest_case()` loads the curated docket metadata; documents
  keyed by content hash (`doc_<sha16>`, matching the exploder).
- **Folder source** — explode a directory of loose `filings/*.pdf` directly, not only a ZIP
  (`inspect_folder` / `inspect_source`); the ZIP path is unchanged.
- **Corpus index** (`index.py`) — index sections + page chunks from the manifest and per-document
  `toc.json`, with a declared-vs-actual page-count cross-check, an atomic (transactional) re-index,
  and an integrity guard on gapless page coverage.
- **`lawnlord query`** — read-only search with provenance: `--text`, `--needs-review`, `--phase`,
  `--event`, `--party`.
- **OCR** (`ocr.py`) — optional `--ocr` / `--gpu` recovers text for scanned pages (RapidOCR; CUDA
  when available, graceful CPU fallback); each page tags `textSource` and `ocrConfidence`. OCR
  text is machine-generated and non-evidential.
- **CLI** — `lawnlord index` ties explode → ingest → index together; `build` gains a folder source
  and `--ocr` / `--gpu`.

### Changed

- Project framing: added `docs/ROADMAP.md` and `docs/plans/`; refreshed `pyproject.toml` metadata
  (description, keywords, trove classifiers, URLs); `.gitignore` ignores `intake/` (case data never
  lives in the tool repo).

### Notes

- Determinism preserved: re-index is byte-identical and row timestamps come from the corpus
  `generatedAt`. Page-analysis legal fields stay human-owned and are never pre-filled.

## [0.1.0] - 2026-06-16

**Release:** not published · **Tag:** none · **Milestone:** none _(predates tagging)_

The first version: a standalone, deterministic legal court-record **exploder**.

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

[0.3.0]: https://github.com/jwogrady/lawnlord/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/jwogrady/lawnlord/releases/tag/v0.2.0
