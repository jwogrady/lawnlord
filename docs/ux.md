# Product North Star

> **Status — background vision, not a UI spec.** lawnlord is **CLI- and data-first**: you run
> commands and get structured artifacts (the bundle, `case.json`, the DuckDB index, motion drafts).
> There is no interactive dashboard, and none is on the v0.4–v0.8 roadmap. This doc captures the
> *experience principles* that keep the tool honest — not screens. For usage and results see the
> [README](../README.md); for the plan see [ROADMAP](../ROADMAP.md) (the GitHub issues per milestone);
> for what shipped see [CHANGELOG](../CHANGELOG.md).

## What the tool is for

lawnlord exists to help one person **understand a case** well enough to act — not to manage
documents. The goal is legal understanding; filings are its final output.

Every interaction should move toward answering four questions:

1. **What happened?** — the mirrored record + the timeline derived from it.
2. **What can be proven?** — evidence, traceable to source pages.
3. **What law applies?** — the user-supplied knowledge base (rules, statutes, CC&Rs).
4. **What should be done next?** — proposed grounds and motions, for the human to decide.

## Experience principles

- **Understanding precedes strategy; strategy precedes drafting.** The tool builds the record, then
  the context, then the proposed analysis, then a draft — it does not jump to a filing.
- **Outputs are computed and explainable, never chat answers.** Every result is a structured
  artifact whose every claim traces to a source page or a cited authority. If it can't be traced, it
  isn't surfaced.
- **The tool proposes; the human decides.** Analysis, grounds, and drafts are accept/decline
  proposals (issue #28). Legal conclusions are never machine-rendered.
- **The knowledge base is *yours*.** Law/authority comes from resources the user curates (links,
  JSON, PDFs) — the tool never auto-researches the law.

## The terminal experience

The product succeeds when, for the real case, it can produce: a complete, searchable, lossless case
record; a timeline of real deadlines derived from the filings and the rules; a defensible
"actual owed" number; and a grounded, citation-backed motion draft — each reviewable, each
traceable, each the human's to accept before it counts.
