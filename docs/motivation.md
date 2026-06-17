# Lawnlord — why it exists and how you use it

> Product context: the problem lawnlord solves, the solution, how you use it, and what you get. For
> usage commands and results see the [README](../README.md); for the plan see
> [ROADMAP](../ROADMAP.md); for what shipped see [CHANGELOG](../CHANGELOG.md). The commit is the
> present.

## The problem

You are in a court case you did not choose and cannot afford to lose. An HOA won a judgment and is
stacking legal and administrative fees on top of the dues you actually owe — and a foreclosure on
your home is the threat behind it. The full record exists, but it is scattered across filings,
scanned PDFs, and two court portals that disagree on formatting. Reading it is slow; *proving*
anything from it is slower; and missing a single deadline can cost you the house. The lawyers who
could untangle it are expensive. So the person with the most at stake is the least equipped to see
the case clearly.

## The solution

Lawnlord turns that pile into a case you can understand and act on. It mirrors the court's filed
record exactly, extracts every page to searchable text, and proves the result is lossless — so
nothing is missed and everything traces back to a real source page. On that trustworthy record it
helps you answer the questions that decide the case:

**What happened? · What can be proven? · What law applies? · What should be done next?**

You supply the law and context it needs (statutes, rules, your CC&Rs) as a knowledge base; lawnlord
*proposes* analysis and you accept or decline it. It never renders a legal conclusion for you — it
makes you fast and certain enough to render your own.

> The goal is not document management, and not document generation. It is **understanding** — deep
> enough to produce exceptional filings. Understanding precedes strategy; strategy precedes drafting;
> drafting is the final output of understanding.

## How you use it

1. **Create the case** and drop your intake (the court export + filings) into its folder.
2. **Build** — lawnlord explodes every filing into pages, OCRs the scanned ones, and indexes the
   whole `case → event → image → document → page` model into DuckDB.
3. **Bundle** — get one self-contained, cross-linked package: the metadata wrapper, the preserved
   originals, a lossless master PDF, per-page searchable text, and the queryable index.
4. **Search the record** — full-text search with provenance (`query`): every hit traces to its
   source page.
5. **Curate the knowledge base** — add the statutes, rules, and governing documents the case turns
   on, as links / JSON / PDFs.
6. **Review proposed analysis** — accept or decline machine-proposed facts, deadlines, and grounds;
   only what you accept counts.
7. **Get the number and the motions** — a defensible "what is actually owed," and grounded motion
   drafts (e.g. to set aside a judgment), every statement traceable to evidence and authority — for
   you to review and file.

Steps 1–4 ship today. The computed deadline **timeline** (filing dates + court rules), the
**knowledge base** (5), **accept/decline analysis** (6), and the **number + motions** (7) are the
prerequisite chain in the [ROADMAP](../ROADMAP.md) — never from dates you type in.

## What you get

- A **complete, searchable, lossless** record of the case — provably nothing dropped.
- **Provenance on everything** — every fact, page, and citation traces to its source.
- A **timeline of real deadlines** computed from the record and the rules.
- A **defensible number** — the dues you actually owe, with improper fees separated out.
- **Grounded drafts** — motions and a settlement basis, supported by evidence and authority.
- **Understanding before drafting** — you act from a clear picture, not a guess.

## What makes it trustworthy

- **Mirror exactly, add only.** The filed record is immutable; analysis is layered on top and can
  never alter it or its provenance.
- **Two inputs, kept separate.** The case (what *is*) and your curated knowledge base (the law and
  context *you* supply) never blur together.
- **The tool proposes; you decide.** Legal conclusions are human work — surfaced and supported, not
  rendered. Success is measured by the quality of understanding reached before any filing.
