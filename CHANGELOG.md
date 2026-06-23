# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This changelog is the documented state **after** each release — what shipped. Planned work (the
state *before* a release) lives in the [ROADMAP](ROADMAP.md); the current working state is
always the commit. Each release below links to its **release milestone** and the **issues** it
closed.

## [Unreleased]

### Added

- **Diff-highlighting in the comparison viewer** (#126). Each transcription column in the Exploded
  lens now highlights the tokens that **diverge from the canonical anchor**, and flags readings that
  fall below the agreement/fidelity thresholds with an inline ⚑. The diff spans and the flag come
  from the export layer (`export-exploded` now carries a per-reading `flagged` boolean alongside the
  existing `divergence`/`agreement`, decided with the same thresholds the metrics rollup uses) — the
  viewer only renders them, never re-diffing or re-scoring client-side. Refs ADR-0008.
- **Fully-exploded QA comparison viewer** (#125). The Exploded lens is now a per-page comparison
  grid that QA's the whole transcription corpus: each page image sits beside **one column per
  variation present** — the PDF text layer and every vision model's reading — read straight from
  `export-exploded` (never re-derived). The canonical record (the PDF text layer) is styled
  **unmistakably apart** from derived AI readings so nothing derived can pass as the record, and
  missing/failed/empty readings now show **explicitly** (an empty-string reading no longer renders
  as "untranscribed"). Navigation spans all five levels — **case → filing → image → document →
  page** — via a breadcrumb, with images grouped under the filings that filed them. To support the
  filing level, `export-exploded` now carries each image's `filings` (the events that filed it, via
  `image_events`) as read-only mirror data.
- **Transcription provenance in the Exploded lens** (#108). `export-exploded` now carries each
  page's transcription `source` (`pdf_text` = exact text from the PDF's own layer, `ai` = a vision
  model's reading), `model`, and `fidelity` alongside the text — read-only, latest revision per
  page. The viewer renders a badge beside each page distinguishing extracted ground truth (**PDF
  text layer**) from an AI reading (**AI · model · fidelity**), so a reader of legal records isn't
  shown both flattened as one.

## [0.4.0] - 2026-06-22 — alpha pivot: the zip is the intake standard

**Branch:** `refactor/zip-standard-intake` · **Backup of the prior state:** the `alpha` branch.

A deliberate teardown to rebuild on a verified foundation. The intake standard is now the
**deterministic `rake` zip** (`schema.json` + `data.json` + `files/` + `pages/`) — the single source
of truth, self-verifying via per-file sha256, with DuckDB built from it **exclusively**. Mirror the
record exactly; everything else is additive — and all the additive layers were removed here so they
can be reimplemented cleanly over the zip (see the [ROADMAP](ROADMAP.md) *Reimplementation backlog*).

### Added

- **Exploded lens — browse inside each filed PDF** (foundation F5, #96). A third viewer lens
  (Actual ↔ Odyssey snapshot ↔ **Exploded**): navigate case → image → document → page, with each
  page's rendered PNG **beside its AI transcription** (and fidelity), or a "no transcription yet"
  marker. Backed by a read-only `lawnlord export-exploded` (joins documents/pages/transcription →
  JSON, latest revision per page) and a path-safe page-PNG route in the viewer. Completes the
  post-pivot foundation (milestone v0.4.0).
- **`lawnlord transcribe` — AI page transcription** (foundation F4, #95). PNG-per-page → Claude vision
  (`claude-opus-4-8`) transcription, persisted to an **append-only** `page_text` table (rev 0
  immutable; re-runs append a revision). Each row records a **fidelity** signal — the model's
  self-assessment of how completely it read the page (the honest reframing of the folded #70). Cloud
  **opt-in**: runs only when `ANTHROPIC_API_KEY` is set (absent → a clear skip, no crash). `SCHEMA_VERSION`
  → 9. Re-adds the `anthropic` dependency.
- **`lawnlord explode` — the Exploded layer** (foundation F3, #94). Renders every filed PDF's pages
  to PNGs (pypdfium2 + Pillow, deterministic at a fixed DPI) and indexes them as additive `documents`
  (one per image) + `pages` (one per page, with its PNG pointer + sha256) tables — on top of the
  mirror, never mutating it. Declared-vs-rendered page-count mismatches are surfaced. `SCHEMA_VERSION`
  → 8. `import` now materializes the intake under `<case-dir>/intake/` (extract a zip, or copy an
  already-extracted dir) so a case is self-contained. New deps: `pypdfium2`, `pillow`. Verified on the
  real case: 22 documents → 255 page PNGs.
- **Actual lens — the Odyssey-faithful viewer** (foundation F2, #93). A local Bun viewer that
  reproduces the portal from the DuckDB **mirror** (not by re-parsing the zip): case header, parties,
  and the register of actions as a **sortable / filterable** table; each filing opens as its **native
  PDF** with deep-link paging; an "Odyssey snapshot" lens renders the captured `pages/*.html` verbatim
  for side-by-side verification. The lens ends at the image. Data comes from a new read-only
  `lawnlord export-actual` (queries the mirror → JSON). Launch: `cd web && CASE_DIR=<case> bun dev`.
- **`lawnlord import <zip>` — the zip → DuckDB reader** (foundation F1, #92). Extracts a rake intake
  zip safely, **validates `data.json` against the bundled `schema.json`** (fail loud on drift or on
  >1 case), maps it into the `CaseModel`, and builds the per-case DuckDB. The DuckDB schema is now the
  **relational mirror of `data.json`** — seven tables (`cases`, `parties`, `events`, `images`,
  `image_events`, `financials`, `financial_transactions`); the inherited additive tables
  (`case_gaps`, `documents`, `chunks`, `extracted_dates`, `knowledge_documents`) and the
  `cases.confidence` column were dropped. `SCHEMA_VERSION` → 7. Values stored verbatim (typing is a
  later additive view); deterministic (`generated_at` from the manifest's `capturedAt`). Un-stubs
  `workspace.Case.from_intake`. New dep: `jsonschema`.

### Removed

- **Provider adapters** — `ody` / `txe` / `combo` parsing and the `combine` command (`providers.py`,
  `combine.py`, `unify.py`). The zip replaces multi-portal parsing and reconciliation.
- **The entire additive layer** — the Claude page layer (`ai.py`, `analysis_schema.py`), document
  explosion / four-tier boundary detection (`boundaries.py`, `corpus.py`, `index.py`), master-PDF
  reconstruction and packaging (`assemble.py`, `bundle.py`, `pack.py`, `canonical.py`), confidence
  scoring (`confidence.py`), date-fact extraction (`dates.py`), the curation overlay (`curation.py`),
  `--force` review preservation (`preservation.py`), full-text search (`query.py`), and packet
  inspection / reporting (`archive.py`, `reporting.py`).
- **The first-generation web app** (`web/`) — the Original/Enhanced compare reviewer. Its good ideas
  are preserved in the ROADMAP *Reimplementation backlog*, not the code.
- **CLI** — every subcommand except `start` (`report`, `build`, `emit-boundaries`, `index`, `pack`,
  `assemble`, `bundle`, `query`, `timeline`, `compare`, `ocr-page`, `ai-page`, `combine`).
- **Dependencies** — `anthropic`, `pymupdf`, and the `ocr` extra (`rapidocr`, `numpy`).

### Changed

- **`models.py`** now owns the `CaseModel` data contract (relocated from `providers.py`) plus
  `case_slug` / `is_suspicious_entry`. The filed-PDF directory constant is `FILES_DIRNAME = "files"`
  (was `filings/`).
- **`workspace.Case.from_intake`** is a stub pending the zip → `CaseModel` reader (next branch);
  `ingest.ingest_case` consumes the model directly (no `unify`).
- **`intake.py`** describes the deterministic zip rather than a packet + curated files.

### Notes

- Surviving suite: **27 tests** green. The package imports and `lawnlord start` runs; the zip reader,
  the two foundational views (Actual, Exploded), and the re-scoped DuckDB schema are the next
  branches in the [ROADMAP](ROADMAP.md). The DuckDB schema is still the inherited `SCHEMA_VERSION = 6`
  and retains tables the current ingest no longer populates (`documents`, `chunks`, `extracted_dates`,
  `knowledge_documents`) — to be re-scoped to the zip's level.

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
  [v0.3.0 milestone (#1)](https://github.com/jwogrady/lawnlord/milestone/1).

- **`lawnlord assemble` — the lossless explode ↔ reassemble proof.** Reassemble a case's images
  back into one master PDF from the **preserved original images** (immutable, hash-pinned), in
  docket order, under a `FILING → IMAGE → DOC` outline (documents from each image's bookmarks, junk
  references filtered), carrying embedded file attachments across. Writes a `*.manifest.json`
  page→provenance sidecar and verifies page-for-page text fidelity, so "no context lost" is a
  checked invariant, not a claim. Against the real `combo` case: 22 images → one 255-page master,
  text-lossless, 61-entry outline, every page traceable to (image, source page). Design:
  [v0.3.0 milestone (#1)](https://github.com/jwogrady/lawnlord/milestone/1).

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

- Project framing: added project planning docs (roadmap + milestone plans); refreshed `pyproject.toml` metadata
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
