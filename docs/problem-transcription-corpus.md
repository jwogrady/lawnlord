# Problem: the transcription corpus is unverifiable — collapse it to one reading and trust dies upstream

Status: Authoritative — the problem this effort solves.

## Problem

`lawnlord transcribe` collapses each page to a single AI reading: the export
surfaces only the latest revision per page, so the page's text is **unverifiable**.
There is no second opinion, no comparison against the page's exact PDF text layer,
and no visible quality signal — a wrong character and a perfect transcription look
identical downstream.

For a legal record this is the dangerous case. The governing invariant is that the
mirror of the court's record is immutable and every derived layer is additive — which
means an error in the derived text must be made **visible**, never silently smoothed
over. But everything built on top of the page text — cross-linking parties, statutes,
claims, and defenses; the defense and plaintiff analysis lenses; AI analysis driven
over an MCP surface; and ultimately the **generated filing** — anchors to this text.
If the text is wrong or merely unconfirmed, every layer above inherits the rot, and
the human has no way to catch it.

Who it hurts: the person building the case, who must rely on the corpus to act — and
any AI analyst that later reads it to propose strategy or draft a motion.

## Outcome

The corpus is **fully exploded** — navigable `case → filing → image → document →
page` — and every page carries all of its evidence side by side:

- the **canonical source** (the PDF page itself),
- the **page image** (the rendered PNG),
- the **page text layer** (exact text from the file, when the page is born-digital),
- and **every model's transcription** (the cloud model plus each installed local
  vision model — discovered, not hardcoded).

The viewer is a **genuine quality-assurance tool**: it makes data problems visible at
a glance — where a model diverges from the text layer, where fidelity is low, where a
reading is missing — at any level, without the user having to read full text.

Differences between readings are **highlighted in two places**: in the text viewer (a
diff across the columns against the canonical anchor) and — the headline — painted
directly **onto the page image**, so a disagreement is visible exactly where it sits on
the page. The link is interactive: **selecting a transcription — or a span within it —
highlights its corresponding region on the page image** (and the reverse), so any
reading can be located on the page with a click. Where a reading carries no reliable
position information, its highlighting degrades to text-only; a region is never
fabricated.

At **every level** (case / filing / image / document / page) the corpus offers both a
**read-only structured export** (data, a pure function of the DB, for downstream
analysis) and **downloadable artifacts** (the files themselves, for the human and the
record).

The whole is quantified by **aggregate confidence gauges** — coverage, cross-model
agreement, fidelity distribution, and flagged-page counts — rolled up at the case and
image levels, so trust in the corpus is measured, not merely felt.

The point of all of it: a corpus complete and verified enough that proper AI analysis
can stand on it and the filing it ultimately generates can be **trusted**.

## Success criteria

1. Every page shows all available variations (canonical source, page image, text
   layer, every model's transcription), each with its provenance and a quality
   signal; a missing or failed reading shows **explicitly**, never as a silent gap.
2. Divergence is visible — each model against the text layer where one exists, and
   against cross-model consensus where it does not.
3. Canonical source truth is visually unmistakable from derived readings; nothing
   derived can be mistaken for the court's record.
4. The corpus never mutates the mirror; every variation is append-only and
   individually addressable, so downstream analysis can anchor to a specific reading.
5. At every level (case / filing / image / document / page) there is **both** a
   read-only structured export and a download of that level's artifacts.
6. The viewer demonstrably surfaces QA problems (divergence, low fidelity, gaps)
   without the user reading full text — quality is scannable.
7. Aggregate confidence gauges (coverage, agreement, fidelity, flag counts) are
   shown at the case and image levels, derived purely from the corpus.
8. Differences between readings are highlighted **both** in the text viewer and **on
   the page image**; a column without reliable position data degrades to text-only
   highlighting rather than a fabricated region.

## Prior art & reusable assets

- `page_text` already records `source` / `model` / `fidelity` — it is keyed to a
  single lineage per page today, which is the constraint to lift.
- `explode` already renders a deterministic PNG per page.
- `transcribe` already has both a cloud (Claude) and a local (Ollama) vision backend
  and a `measure_case` routine that compares backends — but discards the comparison
  rather than persisting it.
- The provenance distinction (`pdf_text` vs `ai`) is already surfaced in the export
  and viewer — the seed of the canonical-vs-derived separation.
- The Exploded lens viewer already navigates case → image → document → page.
- **Left behind:** the cheapest-first, one-reading-per-page short-circuit
  (ADR-0004). The corpus now wants *every* reading on *every* page for comparison,
  not only the cheapest sufficient one.

## Constraints

- The mirror is immutable; layers are additive; the per-case DuckDB is a derived,
  regenerable, deterministic function of the intake.
- Local-first: cloud transcription is opt-in; local models are discovered from
  whatever the operator has installed.
- The viewer reads the case through the read-only CLI exports and never re-parses the
  intake.

## Non-goals

- The interpretive "why" layer — human accept/decline, and the defense and plaintiff
  analysis lenses (issues #28, #38, #118). This effort is the **factual layer** those
  depend on.
- The entity / relationship graph (#38), the corpus-as-MCP surface (#119), and motion
  generation (the defense-lens milestone). All are downstream and gated on a
  trustworthy corpus; none are built here.
