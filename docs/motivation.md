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

Lawnlord starts from a **deterministic export of your case** — a reproducible, self-verifying scrape
of the court portal (the `rake` zip) — and **sorts it into the schema you need to analyze the case
and fight it**: case → parties/events → filed images → (later) the documents within them. It mirrors
the court's record exactly as the immutable base, so nothing is missed and everything traces back to
a real source page. On that trustworthy record it helps you answer the questions that decide the
case:

**What happened? · What can be proven? · What law applies? · What should be done next?**

You supply the law and context it needs (statutes, rules, your CC&Rs) as a knowledge base; lawnlord
*proposes* analysis and you accept or decline it. It never renders a legal conclusion for you — it
makes you fast and certain enough to render your own.

> The goal is not document management, and not document generation. It is **understanding** — deep
> enough to produce exceptional filings. Understanding precedes strategy; strategy precedes drafting;
> drafting is the final output of understanding.

## How you use it

1. **Create the case** — `lawnlord start` scaffolds the intake folder; drop your deterministic export
   (the `rake` zip — `data.json` + `files/` + `pages/`) into it.
2. **Read the case two ways** *(the foundation, in build)* — the **Actual view** reproduces the
   portal (case header, parties, a sortable/filterable register of actions; each filing opens as its
   native PDF) so you can verify the mirror matches the court; the **Exploded view** digs inside each
   filed PDF and transcribes every page (PNG → AI) into searchable text.
3. **Curate the knowledge base** — add the statutes, rules, and governing documents the case turns
   on, as links / JSON / PDFs.
4. **Review proposed analysis** — accept or decline machine-proposed facts, deadlines, and grounds;
   only what you accept counts.
5. **Get the number and the motions** — a defensible "what is actually owed," and grounded motion
   drafts (e.g. to set aside a judgment), every statement traceable to evidence and authority — for
   you to review and file.

Today `lawnlord start` scaffolds the intake. The zip → DuckDB reader and the two views (step 2), the
**knowledge base** (3), **accept/decline analysis** (4), and the **number + motions** (5) are the
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
