# Roadmap

How lawnlord grows from a deterministic document exploder into a local-first case-understanding
engine. Each item below is written to drop straight into a GitHub issue: an imperative title, the
user-facing outcome, verifiable acceptance criteria, and a suggested label.

**Legend** — labels are the repo defaults: `enhancement` (new capability), `documentation`,
`bug`. Milestones group issues.

---

## Shipped — v0.1.0 (the exploder)

The deterministic document exploder: one PDF (or a ZIP of court PDFs) → an
`archive → submission → document → section → page` corpus with provenance, four-tier boundary
detection, a curation overlay, and `--force` review preservation. See [`CHANGELOG.md`](../CHANGELOG.md).

### Open release-hygiene items (issue-ready)

#### Add an open-source LICENSE
- **Outcome:** the repo and package declare a license so it can be released/distributed.
- **Acceptance:** a `LICENSE` file exists; `pyproject.toml` declares the license; `uv build`
  embeds it; README states the license.
- **Label:** `documentation`

#### Publish the v0.1.0 release
- **Outcome:** v0.1.0 is tagged and released on GitHub.
- **Acceptance:** release commit on `master`; `git tag v0.1.0` pushed; `gh release create v0.1.0`
  with notes from the CHANGELOG; `uv build` artifacts attached or reproducible.
- **Label:** `enhancement` *(outward-facing; do after LICENSE)*

---

## Next — Milestone 1 (v0.2.0): Case Workspace + Case/Event/Document Index

Turn lawnlord into a tool that ingests an **intake provider folder** (first provider: `ody` =
Odyssey, `odyssey.mctx.org`), reads the authoritative case/docket/document metadata, explodes each
document, and builds a DuckDB index of the full **case → event → document → section → page** model.
Full design + schema: [`docs/plans/v0.2.0-milestone-1-case-workspace.md`](plans/v0.2.0-milestone-1-case-workspace.md).
The curated intake JSON is the source of truth; the index never guesses what the metadata states.
The example case lives in the separate **`gcp-hoa-case`** repo; lawnlord runs against its intake
folder (`../gcp-hoa-case/intake/ody`) — case data never lives in the tool repo.

#### F1 — Case workspace + intake-folder resolution (decouple `paths.py`)
- **Outcome:** lawnlord runs against an intake provider folder and a `--case-dir` output root, with
  no `REPO_ROOT` dependency; a `Case` resolves the case from `intake/<provider>/`.
- **Acceptance:** `Case.from_intake("../gcp-hoa-case/intake/ody")` yields caseNumber `25-09-14566`, 3 parties,
  phase-ordered events, and 22 document refs; `grep -rn "REPO_ROOT" src/lawnlord/` is confined to
  `paths.py`; existing tests pass unchanged.
- **Label:** `enhancement`

#### F2 — `lawnlord start` scaffold + intake contract
- **Outcome:** `lawnlord start [dir]` materializes the `case/` skeleton (7 dirs + `manifests/case.json`
  + an `lawnlord.duckdb`) and documents the intake-folder contract.
- **Acceptance:** `lawnlord start /tmp/c` builds the documented tree; re-running is a
  non-destructive no-op.
- **Label:** `enhancement`

#### F3 — Promote the CLI to subcommands
- **Outcome:** `lawnlord start | build | index | query`; all existing exploder flags preserved
  under `build` (alias `explode`); `build` accepts an intake folder or the legacy ZIP.
- **Acceptance:** every existing flag works under `lawnlord build …`; `--help` lists the
  subcommands; current behavior unchanged.
- **Label:** `enhancement`

#### F4 — DuckDB layer + Milestone-1 schema
- **Outcome:** a `db` module opens `case/lawnlord.duckdb` and applies an idempotent, versioned
  schema for `cases / parties / events / documents / document_events / sections / chunks`.
- **Acceptance:** `apply_schema` run twice is a no-op; all M1 tables/columns exist; `duckdb`
  added as a dependency with a cp313 wheel.
- **Label:** `enhancement`

#### F5 — Intake metadata ingestion (Odyssey adapter)
- **Outcome:** parse the Odyssey JSON into `cases`, `parties`, `events`, `documents` (deduped by
  file), and the `document_events` many-to-many join; titles/dates/types come from the JSON.
- **Acceptance:** ingesting `../gcp-hoa-case/intake/ody` yields `cases`=1, `parties`=3, `documents`=22, events
  populated, and many-to-many links correct (e.g. `Final_Summary_Judgment.pdf` under multiple
  events); no PDF parsed in this step.
- **Label:** `enhancement`

#### F6 — Explode + index the corpus (sections, pages, cross-check)
- **Outcome:** explode each `filings/*.pdf` into `case/extracted/corpus/`, index `sections` and
  `chunks` (one row per page) from `manifest.json` + per-document `toc.json`, link each to its
  document, and cross-check declared vs actual page counts.
- **Acceptance:** `count(chunks)` == total exploded pages; every chunk row has `document_id` +
  `source_page_number` + `citation_display`; re-index is byte-identical; page-count mismatches are
  flagged (e.g. MSJ declared 121pp), not hidden; integrity guard fails on a dropped page.
- **Label:** `enhancement`

#### F7 — `lawnlord query`
- **Outcome:** read-only search with provenance — `--text`, `--needs-review` (persisted review
  flag, folds in OCR), and docket dimensions `--event` / `--phase` / `--party`.
- **Acceptance:** `--text "summary judgment"` returns rows with document title + source page +
  citation; `--needs-review` matches persisted flags; `--phase "Summary Judgment"` returns the
  phase's documents; queries never write to disk.
- **Label:** `enhancement`

#### F8 — Milestone-1 tests
- **Outcome:** hermetic tests covering intake parsing, workspace/scaffold, schema, ingestion +
  indexing, and the page-count cross-check.
- **Acceptance:** new `test_intake.py / test_workspace.py / test_db.py / test_index.py` pass; the
  existing suite stays green; a real-data smoke over `intake/ody` is documented.
- **Label:** `enhancement`

---

## Later milestones (epics)

#### M2 — Extraction depth
OCR for image-only pages (`ocrLikelyNeeded`), paragraph chunking (fills the nullable `chunks` span
columns), intake of un-docketed/knowledge files into `knowledgebase/*`, nested-ZIP expansion, and
relocating immutable source PDFs into `artifacts/`. **Label:** `enhancement`

#### M3 — Entity layer
Decompose chunks into Facts/Events/Claims/Citations/**Deadlines** (e.g. parse the Docket Control
Order) into an `entities` table keyed to `chunk` + `document`, AI-written with `needsReview: true`
— never into human-owned legal fields or curated intake metadata. **Label:** `enhancement`

#### M4 — Relationships / case graph
A `relationships` table linking entities and documents (Claim→governed-by→Statute,
Order→creates→Deadline, Response↔MSJ). **Label:** `enhancement`

#### M5 — Reasoning
Timelines (seeded by docket `events`), evidence maps, gap/contradiction analysis into
`analysis_results`, each citing its provenance chain. **Label:** `enhancement`

#### M6 — Drafting + review
Filing generation into `outputs/`, grounded only in facts/evidence/law/procedure, with a review
pass for citation/evidence support. **Label:** `enhancement`

#### M7 — Agents + UX
The conceptual agents (intake/extraction/entity/research/analysis/strategy/drafting/review) as
orchestration, and a read-only dashboard over DuckDB answering the four UX questions. **Label:**
`enhancement`

---

## Open decisions (resolve before/with Milestone 1)

1. **M1 scope** — one PR for F1–F8, or split metadata ingestion (F5) into its own milestone?
2. **Provider vs case naming** — provider folder (`ody`) selects the adapter; case slug =
   `caseNumber`. If one provider holds multiple cases, is the layout `intake/<provider>/<case>/`?
3. **Knowledge base** — all current documents are docketed case artifacts; `knowledge_documents`
   stays structure-only until knowledge materials appear.
