# Contributing

This is a personal, **proprietary** project with a single maintainer (see [`LICENSE`](../LICENSE)).
These are the working rules for how the project is built and maintained — by the maintainer and by
any AI agents working in the repo. The license stays most-restrictive until the project is opened to
contributors or released.

## Where things live (source of truth)

- **Code state → the repo.** The commit is always the present; no document describes the live state.
- **The plan (what's next) → GitHub issues + milestones.** The plan is *the issues assigned to a
  milestone*, not a doc file.
- **History (what happened) → GitHub issues.** The `CHANGELOG` narrates shipped releases; it does
  not replace the issues.
- **Four canonical docs always live in the repo root:** `README.md`, `CHANGELOG.md`, `LICENSE`,
  `ROADMAP.md`.

## Documentation rules

- `README`, `CHANGELOG`, `LICENSE`, `ROADMAP` **always live in the repo root.**
- **Anything under `docs/` must be linked from one of those four root docs.** If it isn't worth
  linking, it doesn't belong.
- **README** = the marketing doc — it demonstrates **usage and results** and is always current with
  the commit/release.
- **ROADMAP** = where we're going (the state *before* a release). It narrates and **links** the
  GitHub issues + milestones; the issues are the plan.
- **CHANGELOG** = where we've been (the state *after* a release). Each entry **links** the issues and
  milestone it shipped.
- The roadmap is *before*, the changelog is *after*, the commit is *now*. When a milestone ships,
  its roadmap entries graduate to the changelog, carrying the same issue/milestone links across the
  boundary.
- **LICENSE** = most restrictive until the project is opened to contributors or released.
- **README is the homepage / present state**, with links to every other doc.
- **`docs/` holds standards and code summaries, kept current or deleted.** `docs/architecture.md`,
  `docs/schema.md`, and `docs/ux.md` are **developer code summaries** — every claim must be
  provable by reading the cited code; if a doc and the code disagree, the **code wins**.
  `docs/motivation.md` is the why (problem & solution) + how the customer uses it and benefits.
- **Aspirational / future design goes on the ROADMAP**, never in the code summaries (and is deleted
  from a doc once it no longer reflects reality).

## Issues, milestones, the plan

- Every issue has: an **imperative title**, a user-facing **outcome**, **verifiable acceptance
  criteria**, and a label that **already exists** in the repo (don't invent label taxonomies).
- Milestones are versioned (`vX.Y.Z`) and built in **prerequisite order** — no jumping a feature
  ahead for urgency. Dependencies are stated explicitly.
- The roadmap and changelog must always reference the relevant issues/milestones.

## Branching & pull requests

- **Never commit substantive work straight to `master` — branch first.** Branch names:
  `feat/<issue>-<slug>`, `docs/<slug>`, `chore/<slug>`, `release/vX.Y.Z`.
- One **focused PR** per change; the PR body says **what + why** and references its issue.
- **Land it — don't park it.** Once a change is verified and approved, merge it promptly so `master`
  reflects the decision. Approved/structural changes must not sit in an open PR.

## Commits

- **Conventional commits:** `type(scope): imperative subject`, subject **under 72 characters**. The
  body explains **why**, not what.
- **No AI attribution anywhere** — no `Co-Authored-By`, no "Generated with", no self-crediting
  language in commit messages, PR bodies, or releases.

## Testing

- `uv run pytest` must be **green before merge**.
- Tests are **characterization tests**: they pin current behavior. A failing test is a behavior
  change to **approve by hand**, not to silently update.

## Releases

- Bump the version in `pyproject.toml`, promote the CHANGELOG `[Unreleased]` section to
  `[X.Y.Z]`, commit, **tag `vX.Y.Z`**, and **publish the GitHub release** with notes from the
  CHANGELOG, linking the milestone.

## Engineering invariants (non-negotiable)

These hold for every code change:

- **The deterministic zip is the single source of truth.** The `rake` export (`schema.json` +
  `data.json` + `files/` + `pages/`) is reproducible and self-verifying (per-file sha256); same input
  → same bytes. DuckDB is built **from it exclusively**.
- **Mirror the court's record exactly.** That mirrored record is the immutable **"what is" map**.
- **Everything else is additive.** No analysis, proposal, overlay, or verdict may mutate the
  mirrored record or its provenance (sha256s, paths, page counts). The zip is the chokepoint —
  nothing is authored in place.
- **Two inputs, kept separate:** the **case** (the "what is" map, derived from the court record) vs
  the **knowledge base** (curated external context the *user* supplies — links, JSON, PDFs).
  Analysis reasons over the case *in the context of* the knowledge base.
- **The timeline is derived from what *is*** — filing dates (the record) + court rules/statutes (the
  knowledge base) → computed deadlines, each citing its rule. Never from user-entered dates.
- **Verify the foundation before analyzing.** The two foundational views (Actual, Exploded) — the
  mirror confirmed against the portal and every page transcribed — are the readiness gate; no
  analysis begins until they hold.
- **The tool proposes; the human decides.** Legal conclusions are never machine-rendered. Analysis
  is accept/decline — `pending` until a human accepts it; only `accepted` is treated as truth.
- **The DuckDB index is a derived, regenerable function** of the intake zip. The database never
  authors content.

## How work flows

The project follows the Spark lifecycle: **Ideate → Plan → Codify → Fix → Ship.** Ideate frames the
problem; Plan turns it into issues + a milestone; Codify implements one issue on a branch; Fix
hardens it; Ship lands the focused PR.
