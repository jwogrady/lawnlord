# ADR-0008: Compute divergence and agreement in the export layer, anchored to the text layer

Status: Accepted
Date: 2026-06-22

## Context

Confidence in the corpus rests on showing *where* readings disagree (highlighted in
the text viewer) and *how much* they disagree (the confidence gauges). "Divergence is
visible" and "cross-model agreement" are load-bearing across the viewer, the exports,
and the future MCP consumer — so the metric must be **defined once** and reported
**consistently** everywhere. ADR-0007 already puts metric computation in the export
layer; this ADR pins *what* is computed and *against what*.

## Decision

For each page, compare every variation against a **canonical anchor**: the `pdf_text`
layer when the page has one, otherwise the cross-model **consensus**. From that
comparison the export layer emits, per variation, a **divergence** (a token/line-level
diff suitable for highlighting) and an **agreement** score (a normalized similarity,
0–1). Aggregate gauges (coverage, mean agreement, fidelity distribution, flag counts)
roll these up at the image and case levels. The exact similarity function is pinned in
the implementing issue; the **locus** (export/CLI layer) and the **anchor rule**
(`pdf_text` else consensus) are decided here. The viewer renders these — it never
computes them.

## Consequences

- The same numbers appear in the viewer, the exports, and any downstream consumer.
- Born-digital pages diff against ground truth (a strong signal); image-only pages
  diff against each other (weaker but honest — surfaced as such, not hidden).
- Deterministic given fixed text (the diff/score are pure functions of the stored
  variations).
- Invariants this must not break: read-only, deterministic, the viewer never derives.

## Alternatives considered

- **Diff client-side in the viewer** — rejected: inconsistent across consumers and
  breaks the read-only-renderer invariant.
- **Anchor on a single designated "reference" model** — rejected: privileges one
  model and hides the very comparison the corpus exists to show.
- **Semantic / LLM-judged agreement** — rejected for this layer: that is
  interpretation, which belongs to the `why` layer (#28), not the factual corpus.
