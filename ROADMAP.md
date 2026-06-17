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

These constrain every issue below. (See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the engineering invariants.)

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

### v0.4.0 — Canonical "is" layer (the readiness gate)
[Milestone #2](https://github.com/jwogrady/lawnlord/milestone/2) · *Mirror exactly, extract all text+meta, reconstruct from the data, prove confidence against both sources.*

- [#34](https://github.com/jwogrady/lawnlord/issues/34) — Settle & implement the `section` level *(decision; gates #31)*
- [#35](https://github.com/jwogrady/lawnlord/issues/35) — Resolve the `document` vocabulary collision: one glossary *(decision; gates #31)* · `documentation`
- [#31](https://github.com/jwogrady/lawnlord/issues/31) — Content schema in DuckDB: per-page text + preserved-page-image pointer
- [#32](https://github.com/jwogrady/lawnlord/issues/32) — Reconstruct `case-master.pdf` **from the data** + burned-in searchable text layer
- [#33](https://github.com/jwogrady/lawnlord/issues/33) — Two-sided confidence: reconstruction vs Odyssey metadata **and** source PDFs → `aiAccessible`
- [#36](https://github.com/jwogrady/lawnlord/issues/36) — Extract deadline/order dates from key documents as provenanced **facts**
- [#30](https://github.com/jwogrady/lawnlord/issues/30) — Factual docket timeline derived from filing dates (what IS)
- [#37](https://github.com/jwogrady/lawnlord/issues/37) — Enforce the additive-only invariant (test-proven)

### v0.5.0 — Knowledge base + computed deadline timeline
[Milestone #3](https://github.com/jwogrady/lawnlord/milestone/3) · *Curated external context the user supplies, plus the real clock derived from the record.*

- [#41](https://github.com/jwogrady/lawnlord/issues/41) — Knowledge-base intake: curated external resources (links, JSON, PDFs) as context
- [#42](https://github.com/jwogrady/lawnlord/issues/42) — Computed deadline timeline: filing dates + KB rules → deadlines (the real foreclosure clock)

### v0.6.0 — Analysis layer: accept/decline + entities + relationships
[Milestone #4](https://github.com/jwogrady/lawnlord/milestone/4) · *The "why" layer — machine-proposed, human-accepted; only `accepted` is truth.*

- [#28](https://github.com/jwogrady/lawnlord/issues/28) — Strategic analysis as accept/decline proposals over an immutable record *(anchor)*
- [#38](https://github.com/jwogrady/lawnlord/issues/38) — Epic: accept/decline mechanism + entity & relationship extraction

### v0.7.0 — The ledger: dues vs fees, actual owed
[Milestone #5](https://github.com/jwogrady/lawnlord/milestone/5) · *The number that decides the case.*

- [#39](https://github.com/jwogrady/lawnlord/issues/39) — Epic: dues vs fees, claimed vs governing-document-authorized, actual-owed

### v0.8.0 — Grounds to set aside + generate motions to file
[Milestone #6](https://github.com/jwogrady/lawnlord/milestone/6) · *Terminal: the supportable case, drafted for human review.*

- [#40](https://github.com/jwogrady/lawnlord/issues/40) — Epic: grounds to set aside (gap/contradiction reasoning)
- [#43](https://github.com/jwogrady/lawnlord/issues/43) — Generate motions to file: set-aside motion + settlement basis, grounded

---

## Long-range vision (beyond the chain)

The prerequisite chain above is authoritative for sequencing; the broader vision folds into those
milestones but is recorded here so it isn't lost (aspirational design lives on the roadmap, not in
the code summaries):

- **Extraction depth** — paragraph chunking, knowledge-base files → v0.4.0 / v0.5.0.
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
