# Prior art: lawnlord's origin in rake-old

This note records where lawnlord came from, so the lineage stays legible. It is
history, not current design — where it disagrees with the shipped code, the code
wins.

## The short version

lawnlord began as one half of an earlier, messier repo called **rake-old**. That
repo tangled two ideas together; they were split clean along a **capture vs.
understand** seam:

- the **acquisition** half (log in, crawl, bundle the court record) became
  **[`rake`](https://github.com/jwogrady/rake)**;
- the **understanding** half (normalize the record, shape it into a case the way a
  human reads it) became **`lawnlord`** — rebuilt clean in Python.

The original single-tool vision (a do-everything "rake" that logs in, extracts,
normalizes, and serves) is captured in the workspace's `ideas.md`. The project
intent **changed** into a two-tool pipeline:

```
rake (acquire, faithful capture)  →  zip bundle  →  lawnlord (understand the case)
```

## Where lawnlord's seed actually lives

rake-old's full history is preserved on GitHub as the provenance archive at
**[`jwogrady/rake-old`](https://github.com/jwogrady/rake-old)**. lawnlord's embryo
is on its `alpha` branch:

- **[`alpha:src/types.ts`](https://github.com/jwogrady/rake-old/blob/alpha/src/types.ts)**
  — the "lawnlord-shaped intake" contract: `CaseSummary`, `CaseHistory`,
  `RegisterOfActions`, `FilingRow`/`Filings`, and the wrapping `IntakeBundle`
  (plus `Party`, `Attorney`, `TimelineEvent`, `Disposition`). This is the case
  model lawnlord exists to populate and present.
- **[`alpha:src/normalize/odyssey.ts`](https://github.com/jwogrady/rake-old/blob/alpha/src/normalize/odyssey.ts)**
  — deterministic Odyssey parsers (`parseCaseDetail`, `parseCaseDocuments`,
  `parseParties`, `parseTimeline`, `normalizeOdyssey`) turning portal HTML into
  that model.
- **[`alpha:BUILD-PROMPT.md`](https://github.com/jwogrady/rake-old/blob/alpha/BUILD-PROMPT.md)**
  — the richest statement of intent. It is written as *rake's* build spec, and it
  explicitly flags that the alpha pass "emits lawnlord-shaped intake and skips
  financials" — i.e. the alpha experiment had already drifted into lawnlord's job,
  which is why the two were separated.

## What carried over vs. what changed

- **Carried over (as intent):** the case-as-structured-record idea, the
  party/timeline/filings/financials shape, and deterministic rule-based Odyssey
  parsing.
- **Changed:** language (TypeScript spike → **Python** clean rebuild); storage
  (ad-hoc → **DuckDB**, schema-versioned); scope (lawnlord now owns
  import → explode → transcribe → export → viewer, far beyond the alpha normalizer);
  and process — lawnlord was rebuilt on the **Spark** issue-driven lifecycle
  (see the workspace `prompt3.md` operating prompt).

For rake's side of the same split, see
[`rake/docs/explanation/prior-art-rake-old.md`](https://github.com/jwogrady/rake/blob/master/docs/explanation/prior-art-rake-old.md).
