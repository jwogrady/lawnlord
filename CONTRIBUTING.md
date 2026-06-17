# Contributing

This is a personal, **proprietary** project with a single maintainer (see [`LICENSE`](LICENSE)).
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

- **Mirror the court's filed schema exactly.** That record is the immutable **"what is" map**.
- **Everything else is additive.** No analysis, proposal, overlay, or verdict may mutate the
  mirrored record or any generated provenance — hashes, page ranges, slugs, boundary
  tier/confidence, paths, or citations. The curation whitelist (`curation.ALLOWED_CURATED_FIELDS`)
  is the only chokepoint.
- **Two inputs, kept separate:** the **case decomposition** (the "what is" map, derived from the
  court record) vs the **knowledge base** (curated external context the *user* supplies — links,
  JSON, PDFs). Analysis reasons over the case map *in the context of* the knowledge base.
- **The timeline is derived from what *is*** — filing dates (the record) + court rules/statutes (the
  knowledge base) → computed deadlines, each citing its rule. Never from user-entered dates.
- **Reconstructable text is the readiness gate.** No analysis begins until every page round-trips
  text + image from the data and clears confidence against both intake sources.
- **The tool proposes; the human decides.** Legal conclusions are never machine-rendered. Analysis
  is accept/decline — `pending` until a human accepts it; only `accepted` is treated as truth.
- **The DuckDB index is a derived, regenerable function** of the intake + corpus. The database never
  authors content.

## How work flows

The project follows the Spark lifecycle: **Ideate → Plan → Codify → Fix → Ship.** Ideate frames the
problem; Plan turns it into issues + a milestone; Codify implements one issue on a branch; Fix
hardens it; Ship lands the focused PR.
