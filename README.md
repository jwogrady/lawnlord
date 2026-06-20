<p align="center"><img src="docs/assets/lawnlord.png" alt="LAWN LORD" width="380" /></p>

# lawnlord

*Mirror a court case from its deterministic export, then build the views you need to read it and fight it — verifiable, and traceable to the source.*

![python](https://img.shields.io/badge/python-3.13%2B-blue)
![tests](https://img.shields.io/badge/tests-27%20passing-brightgreen)
![status](https://img.shields.io/badge/status-alpha%20rebuild-orange)
![license](https://img.shields.io/badge/license-proprietary-red)

A local-first **legal case-understanding engine**. Its single source of truth is the **deterministic
intake zip** produced by [`jwogrady/rake`](https://github.com/jwogrady) — a reproducible scrape of
the court portal (`schema.json` + `data.json` + `files/` + `pages/`), self-verifying via per-file
sha256. lawnlord builds a queryable index **from that zip exclusively** and reproduces the views the
zip's pages already contain.

The governing principle is unchanged: **mirror the court's record exactly as the immutable base, then
everything else is additive** — no analysis or overlay may ever alter the mirrored record or its
provenance.

> **Status: alpha — mid-rebuild.** The project is being re-founded on the zip standard. The previous
> implementation (the document exploder, master-PDF reconstruction, the Claude analysis layer, and the
> first-generation web reviewer) was deliberately removed so it can be reimplemented cleanly on top of
> a verified foundation. The pre-teardown snapshot is preserved on the **`alpha`** branch. See
> [CHANGELOG.md](CHANGELOG.md) for what changed and [ROADMAP.md](ROADMAP.md) for what's next.

## Where it's going

Two foundational views over the zip come first (see the [ROADMAP](ROADMAP.md)):

1. **Actual view — "as if logged into Odyssey."** The case header, parties, and register of actions
   as a sortable/filterable case-history table; each filing opens as its **native PDF**. It ends at
   the image — for visually verifying the mirror matches the portal.
2. **Exploded view — inside each filed PDF.** Case → filing → image → page, with each page
   transcribed from a PNG render via AI (not OCR), shown beside the page image.

Everything beyond these — cross-referencing, case linking, argument tagging, the analytical lenses —
builds on that substrate and is sequenced in the ROADMAP.

## What's in the repo today

A stripped, importable foundation (the zip-view "studs"):

- **`models.py`** — the `CaseModel` data contract the zip reader will populate (case → parties →
  events → documents), plus pure helpers (`case_slug`, `is_suspicious_entry`).
- **`db.py`** — the per-case DuckDB index (idempotent, versioned schema).
- **`ingest.py`** — map a `CaseModel` into the DuckDB docket tables (cases, parties, events, images,
  image↔event links, financials).
- **`intake.py`** — the intake-folder contract (the deterministic zip) + `lawnlord start` scaffold.
- **`workspace.py`** — the resolved `Case` (its model + output paths). `from_intake` is a stub
  awaiting the zip → `CaseModel` reader (the next branch).

## Install

```bash
uv add lawnlord                      # as a project dependency
# or, for local development from a sibling checkout:
#   [tool.uv.sources] lawnlord = { path = "../lawnlord", editable = true }
```

## Usage

```bash
lawnlord start [root]    # scaffold intake/ + lawnlord.toml + an intake README
```

The intake location is configurable so case data can live in a **separate repo** or **local in the
project**, resolved in this order: the `LAWNLORD_INTAKE` env var → `lawnlord.toml`'s `[lawnlord]
intake` → `./intake`. `python -m lawnlord …` works as an alternative to the console script.

### Intake layout

```text
<root>/
  lawnlord.toml          # optional config: intake/corpus dir names
  intake/
    <case>.zip           # the deterministic rake export (the single source of truth)
  corpus/                # generated output (regenerable)
```

The zip itself contains:

```text
data.json      the case record (case → documents → register of actions → parties → financial)
schema.json    the JSON Schema describing data.json
manifest.json  per-file sha256 + source URLs + capture metadata
files/         the filed PDFs (doc-<id>.pdf)
pages/         the captured portal HTML (CaseDetail.html, CaseDocuments.html)
```

## What's guaranteed

- **Deterministic source of truth.** The intake zip is reproducible and self-verifying (per-file
  sha256); DuckDB is a derived, regenerable function of it and never authors content.
- **Mirror exactly, then add.** lawnlord reproduces the court's record as the **immutable record**;
  all analysis is *additive* and can never alter the mirrored record or its provenance.
- **Human-owned legal conclusions.** The tool surfaces and *proposes*; the human decides. Legal
  conclusions are never machine-rendered.

## Development

```bash
uv run pytest                        # characterization suite (27 tests)
```

The tests are **characterization tests**: they pin current behavior, so a failing test is a behavior
change to approve by hand, not to silently update.

## Documentation

- [`docs/motivation.md`](docs/motivation.md) — the problem, the solution, and how you use it.
- [`docs/architecture.md`](docs/architecture.md) — modules, data flow, the DuckDB schema, invariants.
- [`docs/schema.md`](docs/schema.md) — the zip's `data.json` standard + the DuckDB schema.
- [`docs/ux.md`](docs/ux.md) — the CLI and user-facing behavior.
- [`docs/contributing.md`](docs/contributing.md) — the doc model, conventions, and engineering invariants.
- [`docs/brand/brand-guide.md`](docs/brand/brand-guide.md) — palette, tokens, fonts, swatch sheet.
- [`ROADMAP.md`](ROADMAP.md) — where we're going · [`CHANGELOG.md`](CHANGELOG.md) — where we've been.

## License

Proprietary — © 2026 jwogrady. **All rights reserved.** This repository is published for reference
and transparency only; no permission is granted to use, copy, modify, or distribute the software or
its source. See [`LICENSE`](LICENSE).
