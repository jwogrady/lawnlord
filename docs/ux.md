# User-facing behavior (developer code summary)

> **Provable from the code.** Every command, flag, and output below is what `cli.py` and its
> handlers (`_cmd_*`) actually do. If this doc and the code disagree, **the code wins.** lawnlord is
> CLI- and data-first; the only UI is the read-only local viewer in `web/`. Planned features live in
> the [ROADMAP](../ROADMAP.md).

Entry points: the `lawnlord` console script and `python -m lawnlord` (`__main__.py`), both call
`cli.main()`. `main` sources a project-local `.env` (so `ANTHROPIC_API_KEY` etc. need not be exported
by hand) and reports known input errors (`FileNotFoundError` / `ValueError`) as a clean message + exit
1, no traceback.

## Subcommands (`cli.py`)

Ten subcommands are registered in `build_parser` / the `COMMANDS` map. Every command but `start` and
`import` resolves the case from `--case-dir` (default cwd) holding `lawnlord.duckdb`. The four
`export-*` commands emit JSON only on stdout (so the viewer can parse them) and open the DB read-only.

| Command | Args / key flags | Writes | Read-only |
|---|---|---|---|
| `start` | `root` (default cwd); `--force` | `intake/`, `lawnlord.toml`, `intake/README.md` | no |
| `import` | `source` (zip or extracted dir); `--case-dir` | `intake/<stem>/`, `lawnlord.duckdb` (the mirror) | no |
| `explode` | `--case-dir`; `--dpi` (default 150) | `documents` + `pages` rows; page PNGs under `extracted/pages/` | no |
| `transcribe` | `--case-dir`; `--backend {all,cloud,local,llamacpp}`; `--model`; `--ollama-host`; `--llamacpp-host`; `--force`; `--workers`; `--max-image-px`; `--escalate-below`; `--log-level` | `page_text` rows (append-only); a run log under `logs/` | no |
| `regions` | `--case-dir` | `page_regions` rows (PDF geometry) | no |
| `measure` | `--case-dir`; `--models`; `--cloud`; `--sample` (default 10); `--ollama-host` | nothing (prints a comparison table) | yes |
| `export-actual` | `--case-dir` | — (JSON to stdout) | yes |
| `export-exploded` | `--case-dir`; one of `--filing` / `--image` / `--document` / `--page` | — (JSON to stdout) | yes |
| `export-metrics` | `--case-dir`; `--image` | — (JSON to stdout) | yes |
| `export-regions` | `--case-dir`; `--page` (required) | — (JSON to stdout) | yes |

### What each command does

- **`start`** — `scaffold` writes the intake folder under `root`: the `intake/` dir, a starter
  `lawnlord.toml`, and an intake README explaining the deterministic zip is the single source of truth.
  Existing files are left alone unless `--force`.
- **`import`** — materializes the intake under `<case-dir>/intake/<name>` (a zip is extracted safely; an
  already-extracted dir is copied in), reads + validates it via `Case.from_intake`, then builds the
  DuckDB mirror with `ingest_case`. Prints a Rich table of the imported counts (parties, events, images,
  links) and flags images skipped for a missing source PDF.
- **`explode`** — renders every filed PDF's pages to deterministic PNGs (pypdfium2 at `--dpi`) and
  populates `documents` (one per image today) + `pages`. Surfaces declared-vs-rendered page-count
  mismatches and PDFs that were skipped.
- **`transcribe`** — runs the vision tier(s) over each page PNG and appends `page_text` rows. `--backend
  all` (default; ADR-0006) is the exhaustive set: cloud Claude when `ANTHROPIC_API_KEY` is set, plus
  every installed Ollama vision model. `cloud` / `local` / `llamacpp` narrow to one tier; `--model` pins
  a single model. The PDF text layer is read for born-digital pages regardless. `--escalate-below T`
  re-transcribes the local tier's pages with fidelity < T on cloud Claude (ADR-0001). `--force`
  re-transcribes already-done pages (appending a revision). Cloud is opt-in: with no key and no local
  model, it prints why and skips.
- **`regions`** — captures the spatial-anchor layer (`page_regions`): one normalized box per
  whitespace token of each born-digital page's `pdf_text`, from the PDF's glyph geometry, only when the
  stored text still matches the PDF — never fabricated (ADR-0009).
- **`measure`** — read-only backend comparison: samples image-only pages and prints each backend's
  average fidelity and the share of pages below several escalation thresholds. Exits 1 if no backend is
  available.
- **`export-actual`** — the Actual-lens view (case header + parties + register of actions + documents),
  straight from the mirror.
- **`export-exploded`** — the Exploded-lens view (images → documents → pages, each page carrying every
  transcription variation). With no selector, the whole case; one of `--filing`/`--image`/`--document`/
  `--page` scopes it to that node (ADR-0007).
- **`export-metrics`** — divergence/confidence rollups (coverage, mean agreement, per-model fidelity,
  flagged pages) at the case and image levels (ADR-0008).
- **`export-regions`** — the spatial-anchor regions (normalized boxes per span) for one `--page`, for
  the on-image highlight renderer.

## Intake-root resolution (`cli._resolve_intake`, `cli._intake_root`)

So case data can live in a separate repo or local in the project, an intake folder is resolved as an
explicit path (used as-is) **or** a bare name under the configured intake root, in this order:

1. `LAWNLORD_INTAKE` env var,
2. `lawnlord.toml`'s `[lawnlord] intake` (absolute or relative to the project),
3. `./intake` (the in-project default).

## The viewer (`web/`)

A local, single-user Bun app — a lens switcher (Actual / Odyssey snapshot / Exploded) over the same
immutable record. It reads the case **only** through the `export-*` CLI commands above (never by
re-parsing the zip) and serves the filed PDFs, the captured Odyssey `pages/*.html`, and the page PNGs
from disk. It binds to loopback by default. Run it against a built case:

```sh
cd web && CASE_DIR=/path/to/case bun dev
```

## Not built yet (see the ROADMAP)

There is no analysis or accept/decline UI; the viewer is read-only. Those are the near-term work in the
[ROADMAP](../ROADMAP.md); they are not callable today.
