# compare reviewer

A local, single-user **desktop** tool: review a case **page by page**, comparing the
**actual** original filing against lawnlord's **reconstructed** page (from the data, #32). Each
page shows lawnlord's **score** and a short **note** on top; you then **rate** it (good–bad range),
add **notes**, and **flag** it. Completing a page marks it **human-reviewed** — the workflow is
compare → rate → notate → flag, all in one. The point is to feel the **gap** between lawnlord's
score and your own experience.

## Run

```bash
cd web
bun install
bun dev            # → http://localhost:4173  (bun --hot index.ts)
```

It opens on the bundled **sample** out of the box. To review a real case, point it at a compare
artifact:

```bash
COMPARE_DIR=/path/to/case/compare bun dev
```

## Data contract

`COMPARE_DIR` (default: `./sample`) holds:

- `compare.json` — `{ case, pages: [{ id, image, page, actual, reconstructed, score, note }] }`,
  where `actual`/`reconstructed` are image URLs under `/images/…`.
- `images/` — the per-page renders (actual + reconstructed).
- `review.json` — **written by the tool** (your ratings, notes, flags, `reviewed: true`); gitignored.

A `lawnlord compare` emitter (next) produces `compare.json` + `images/` from a real case (the actual
original pages, the reconstructed master pages, and the #33 confidence as the score). Until then the
sample demonstrates the workflow.

## Stack

Bun + TypeScript, vanilla DOM, served by `Bun.serve` (HTML import; no framework/bundler). Lint/format
via Biome.
