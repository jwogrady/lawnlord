# Roadmap

How lawnlord grows from a deterministic document exploder into a local-first
case-understanding engine — and, for the case it was built around, into the
substrate for a specific litigation outcome.

This roadmap is the documented state **before** a release — what's planned. Its mirror is the
[CHANGELOG](CHANGELOG.md), the documented state **after** a release — what shipped. The current
state is always the commit; neither document describes the live present. When a milestone ships, its
entries here graduate to the changelog, carrying the same issue and milestone links across the
boundary.

**The plan itself is the GitHub issues** assigned to each milestone; this roadmap narrates them.
Every planned item links to its **GitHub issue** and its **release milestone** so this document and
the tracker stay in sync. Issues: <https://github.com/jwogrady/lawnlord/issues> ·
Milestones: <https://github.com/jwogrady/lawnlord/milestones>.

---

## The end goal

> **Stop the foreclosure → know the real number → set aside the judgment → settle for actual dues only.**

For HOA case `25-09-14566`: set aside the judgment and settle for only the actual annual dues
owed — no legal fees, no administrative fees. Protecting the house from foreclosure is the first
priority; "winning" means paying what is actually owed. The tool's job is **understanding** — it
surfaces and *proposes*; the human decides. Legal conclusions are never machine-rendered.

The work is sequenced as a **prerequisite chain** that terminates in generating motions to file —
not by jumping features ahead for urgency, but by building each layer on the one beneath it.

---

## Governing principles

These constrain every issue below. (See [`docs/contributing.md`](docs/contributing.md) for the engineering invariants.)

1. **Mirror the court schema exactly.** Explode each source to the court-level schema as it lives in
   the originating system. That mirrored record is the immutable **"what is" map**.
2. **Everything else is additive.** No analysis, proposal, overlay, or verdict may ever mutate the
   mirrored record or its generated provenance (hashes, page ranges, slugs, tier/confidence, paths,
   citations). Enforced by the `ALLOWED_CURATED_FIELDS` whitelist (`curation.py`).
3. **Two inputs, kept separate.**
   - **Case decomposition** = the "what is" map, derived from the court's filed record. Evidence.
   - **Knowledge Base** = curated context *the user supplies* — website links, JSON, PDFs that live
     *outside* the case (court rules, statutes, CC&Rs, guidance). Authority/context, not evidence.
   Analysis reasons over the case map *in the context of* the knowledge base.
4. **The timeline is derived from what *is*.** Filing dates (the record) + court rules/statutes (the
   knowledge base) → computed deadlines, each citing the rule that produced it. Never from
   user-supplied dates.
5. **Reconstructable text is the readiness gate.** When every page round-trips text + image from the
   data and clears confidence against both intake sources, the case is `aiAccessible` — and only
   then does legal analysis begin.

---

## Shipped

| Version | What | Links |
|---|---|---|
| **0.3.0** | Complete-truth schema + bundle capstone — auto-OCR, BM25 search, lossless reassembly proof, field-complete mirror readers, canonical `case.json` v2.0, DuckDB standard schema, `lawnlord bundle`. | Milestone [v0.3.0 (#1)](https://github.com/jwogrady/lawnlord/milestone/1) · Tag [v0.3.0](https://github.com/jwogrady/lawnlord/releases/tag/v0.3.0) · Issues [#14](https://github.com/jwogrady/lawnlord/issues/14)–[#20](https://github.com/jwogrady/lawnlord/issues/20) |
| **0.2.0** | Case workspace + Odyssey adapter, DuckDB index, `lawnlord query`, OCR, folder source. | Release [v0.2.0](https://github.com/jwogrady/lawnlord/releases/tag/v0.2.0) |
| **0.1.0** | The deterministic exploder: `archive → submission → document → section → page` with provenance, 4-tier boundary detection, curation overlay, `--force` review preservation. | _Never tagged or released (see Release hygiene)_ |

See [`CHANGELOG.md`](CHANGELOG.md) for full detail.

---

## The path ahead — prerequisite chain

Build top to bottom. Each milestone depends on the one above it.

> **Direction change — alpha track (2026-06).** The intake standard is now the **deterministic
> `rake` zip** (`schema.json` + `data.json` + `files/` + `pages/`): the single source of truth,
> self-verifying via per-file sha256, with DuckDB built from it **exclusively**. The provider
> adapters (`ody`/`txe`/`combo`) and the **entire additive layer** — analysis, the Claude page
> layer, document explosion (boundary detection), master-PDF reconstruction, confidence scoring,
> curation overlay, review preservation, full-text search, and the compare/review **web app** — were
> removed to rebuild on a verified foundation. The pre-demolition snapshot is preserved on the
> **`alpha`** branch. The milestones below are unchanged in *intent*; they are now **rebased** to sit
> on top of the two foundational views, and their additive pieces will be **reimplemented over the
> zip** (see *Reimplementation backlog*). The principle is unchanged: mirror exactly, then add.

### v0.4.0 — Foundation: zip import + Actual & Exploded lenses
[Milestone #8](https://github.com/jwogrady/lawnlord/milestone/8) · *Recreate exactly the views the
zip's pages already contain — nothing additive. Each page of the zip is the data-view contract. The
substrate that cross-referencing, case linking, and argument tagging build on, so it ships first and
alone.* Five ordered, codify-sized steps (each builds on the last):

- **[F1 · #92](https://github.com/jwogrady/lawnlord/issues/92) — Import the zip → CaseModel + DuckDB**
  *(un-stubs `workspace.from_intake`)*. The DuckDB schema is the **relational mirror of the zip** —
  `data.json`, formally described by the zip's own `schema.json`:
  - **Read** — extract the zip safely (`is_suspicious_entry` on every entry), **validate `data.json`
    against the bundled `schema.json`** (fail loud if the zip drifts from its own contract), then map
    into `models.CaseModel`. This replaces the deleted provider adapters.
  - **Honor the schema, don't codegen from it** — `schema.json` is the contract to validate against;
    the relational DDL is hand-authored (JSON-Schema→SQL auto-generation is brittle: nested arrays
    become child tables, and every field is typed `string`).
  - **Mirror stores values verbatim** — `schema.json` types everything as `string`
    (`"Page Count": "6"`, `"366.00"`, `"09/05/2025"`); the mirror keeps the raw strings — that *is*
    the immutable base. Typed/normalized values (numbers, ISO dates) are a **derived/additive** view,
    never the mirror (keeps "mirror exactly, then add" honest at the DB layer).
  - **Re-scope the schema to the zip** — keep the seven tables that mirror `data.json`
    (`cases`, `parties`, `events`, `images`, `image_events`, `financials`, `financial_transactions`);
    **drop the four inherited additive tables** (`documents`, `chunks`, `extracted_dates`,
    `knowledge_documents`). The page-text/transcription layer returns at F3/F4 as a clearly-additive
    layer, not in the mirror.
  - Bump `SCHEMA_VERSION`; per-case DBs are regenerable, so no in-place migration.
- **[F2 · #93](https://github.com/jwogrady/lawnlord/issues/93) — Actual lens ("as if logged into
  Odyssey").** A faithful reproduction of the portal: case header (caption, court, judge, status,
  filed date), parties, and the register of actions as a **sortable / filterable** case-history table
  (date · type · party · page count · linked doc). Each filing opens as its **native PDF** (selectable
  text, real paging — *not* a render), deep-link paged (`#page=N&view=FitH`). **Ends at the image.**
  Also renders the captured `pages/*.html` verbatim for true snapshot parity. Purpose: visually
  verify LawnLord matches Odyssey.
- **[F3 · #94](https://github.com/jwogrady/lawnlord/issues/94) — Explode the images.** Split each
  filed PDF into its documents and pages; render each page to a PNG; persist an **additive**
  documents/pages index (never mutating the F1 mirror). Surface declared-vs-rendered page-count
  mismatches (flagged, never hidden).
- **[F4 · #95](https://github.com/jwogrady/lawnlord/issues/95) — Transcribe each page.** PNG render →
  **AI transcription** (not OCR — materially more accurate); append-only (rev 0 immutable); a per-page
  **transcription-vs-image fidelity** signal (the honest reframing of the folded #70). Cloud opt-in
  (`ANTHROPIC_API_KEY`).
- **[F5 · #96](https://github.com/jwogrady/lawnlord/issues/96) — Exploded lens.** Lens switch Actual ↔
  Exploded; navigate case → filing → image → page; page image **beside its transcription**; document
  grouping; integrity flags.

> **Lenses as labels.** Every issue carries `lens:*` / `layer:*` labels (`lens:actual`,
> `lens:exploded`, `lens:defense`, `lens:plaintiff`, `layer:foundation`, `layer:platform`) so the
> tracker reads by lens as well as by milestone. Deferred: the Plaintiff lens, the lens-switcher as
> its own issue, and the analysis-mechanism split — out of the foundation loop on purpose.

### v0.4.0 (superseded) — Canonical "is" layer
[Milestone #2 (closed)](https://github.com/jwogrady/lawnlord/milestone/2) · **Superseded by the alpha
pivot.** This is-layer (content schema, reconstruct-from-data, two-sided confidence, date facts;
issues #30–#37) was built then **removed** when the rake zip became the sole standard. Where it still
matters, it re-expresses on the zip: the mirror is now **F1 (#92)**; per-page text + fidelity is
**F3/F4 (#94/#95)**; the additive-only invariant now rides on the immutable zip. Closed for history.

### v0.4.1 (superseded) — Compare & review UI
[Milestone #7 (closed)](https://github.com/jwogrady/lawnlord/milestone/7) · **Superseded by the alpha
pivot.** The first-generation web reviewer ([#66](https://github.com/jwogrady/lawnlord/issues/66),
[#67](https://github.com/jwogrady/lawnlord/issues/67)) was deleted; the logo
([#68](https://github.com/jwogrady/lawnlord/issues/68)) survives. [#70](https://github.com/jwogrady/lawnlord/issues/70)
folded into **F4 (#95)**. The review/lens UI returns as **F2/F5 (#93/#96)** plus the lens switcher.
Closed for history.

### v0.5.0 — Local-first transcription
[Milestone #9](https://github.com/jwogrady/lawnlord/milestone/9) · *The `aiAccessible` readiness gate
(principle #5): reconstructable, high-fidelity page text is the prerequisite every analysis layer
below depends on — so it ships before the knowledge base.* Make transcription **local-first** on the
GPU with **fidelity-gated cloud escalation** — fast, cheap, resumable, decided by measured fidelity.
See [`docs/problem-transcription-efficiency.md`](docs/problem-transcription-efficiency.md) and
[`docs/adr/0001`–`0003`](docs/adr/).

### v0.6.0 — Knowledge base + computed deadline timeline
[Milestone #3](https://github.com/jwogrady/lawnlord/milestone/3) · *Curated external context the user supplies, plus the real clock derived from the record.*

- [#41](https://github.com/jwogrady/lawnlord/issues/41) — Knowledge-base intake: curated external resources (links, JSON, PDFs) as context
- [#42](https://github.com/jwogrady/lawnlord/issues/42) — Computed deadline timeline: filing dates + KB rules → deadlines (the real foreclosure clock)

### v0.7.0 — Analysis layer: accept/decline + entities + relationships
[Milestone #4](https://github.com/jwogrady/lawnlord/milestone/4) · *The "why" layer — machine-proposed, human-accepted; only `accepted` is truth.*

- [#28](https://github.com/jwogrady/lawnlord/issues/28) — Strategic analysis as accept/decline proposals over an immutable record *(anchor)*
- [#38](https://github.com/jwogrady/lawnlord/issues/38) — Epic: accept/decline mechanism + entity & relationship extraction

### v0.8.0 — The ledger: dues vs fees, actual owed
[Milestone #5](https://github.com/jwogrady/lawnlord/milestone/5) · *The number that decides the case.*

- [#39](https://github.com/jwogrady/lawnlord/issues/39) — Epic: dues vs fees, claimed vs governing-document-authorized, actual-owed

### v0.9.0 — Grounds to set aside + generate motions to file
[Milestone #6](https://github.com/jwogrady/lawnlord/milestone/6) · *Terminal: the supportable case, drafted for human review.*

- [#40](https://github.com/jwogrady/lawnlord/issues/40) — Epic: grounds to set aside (gap/contradiction reasoning)
- [#43](https://github.com/jwogrady/lawnlord/issues/43) — Generate motions to file: set-aside motion + settlement basis, grounded

---

## Reimplementation backlog — ideas preserved from the alpha demolition

Good ideas from the removed code (chiefly the first-gen web app), kept so they aren't lost. These
are **patterns to carry forward**, not live features; they fold into the milestones above as the
additive layer is rebuilt over the zip.

**Actual-view UX (carry into the Foundation)**
- **Mode/lens switcher** — the Original vs Enhanced toggle (persisted to `localStorage`); generalize
  to a lens switcher (Actual → Exploded → later analytical lenses) over the same immutable record.
- **Register of actions as the case TOC** — a left rail in docket order, each row showing
  date · type · party · page count, the current filing highlighted; click to open. Becomes the
  sortable/filterable case-history table.
- **Native-PDF viewing, not a render** — open the court's actual filed PDF (selectable text, real
  paging) with deep-link paging (`#page=N&view=FitH`).
- **Page pills** — one pill per declared page; clicking parks the viewer on that page.

**Exploded-view UX**
- **Case → filing → image → page rail**, grouping pages under their filed image (`filingGroups`).
- **Page text beside the page image**, with the text source labelled.
- **Integrity surfaced, never hidden** — rendered vs declared page counts; mismatches flagged (⚑).

**Additive layers (deferred — reimplement over the zip, per their milestones)**
- **AI page layer** → transcription is **F4 (#95)**; summary/analysis as **accept/decline proposals**
  ([#28](https://github.com/jwogrady/lawnlord/issues/28), v0.6.0) that never overwrite the record —
  transcription lands as a revision, analysis as a pending proposal.
- **Human review signal** → v0.6.0: rate 0–100 (good–bad), note, flag, mark-reviewed; the **gap vs
  lawnlord's own analysis** is the point.

**Engineering patterns worth keeping**
- **Append-only revision history** — rev 0 is the immutable original; every re-extract / human edit
  / revert **appends** a revision and never overwrites. Strong, auditable provenance — adopt
  wherever text gets corrected.
- **Local single-user server** — Bun + HMR, per-artifact JSON endpoints, additive state (reviews /
  revisions / proposals) persisted in files **separate** from the immutable record.

## Long-range vision (beyond the chain)

The prerequisite chain above is authoritative for sequencing; the broader vision folds into those
milestones but is recorded here so it isn't lost (aspirational design lives on the roadmap, not in
the code summaries):

- **Extraction depth** — page transcription is F3/F4 (#94/#95); paragraph chunking + knowledge-base files → v0.5.0.
- **Entity layer** — Facts / Events / Claims / Citations / Deadlines, extracted with provenance → v0.6.0 ([#38](https://github.com/jwogrady/lawnlord/issues/38)).
- **Relationships / case graph** — Claim→governed-by→Statute, Order→creates→Deadline → v0.6.0 ([#38](https://github.com/jwogrady/lawnlord/issues/38)).
- **Reasoning** — timelines, evidence maps, gap/contradiction analysis → v0.5.0 ([#42](https://github.com/jwogrady/lawnlord/issues/42)), v0.8.0 ([#40](https://github.com/jwogrady/lawnlord/issues/40)).
- **Drafting** — grounded motions and a settlement basis → v0.8.0 ([#43](https://github.com/jwogrady/lawnlord/issues/43)).
- **Agents & a read-only view** — the conceptual agents (intake/extraction/entity/research/analysis/strategy/drafting/review) are *execution tools* that propose for human accept/decline — they never decide. Not yet built.

What *is* built is summarized in [`docs/architecture.md`](docs/architecture.md).

---

## Release hygiene

- ✅ **`LICENSE` added** — proprietary, all rights reserved. Declared in `pyproject.toml`
  (`license = { file = "LICENSE" }` + the `License :: Other/Proprietary License` classifier), stated
  in the README, and embedded by `uv build`.
- ✅ **v0.3.0 released** on GitHub ([release](https://github.com/jwogrady/lawnlord/releases/tag/v0.3.0)).
- **v0.1.0 was never tagged or released.** Only `v0.2.0` and `v0.3.0` are tagged; backfilling a
  `v0.1.0` tag is optional and low-priority.
