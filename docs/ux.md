# User-facing behavior (developer code summary)

> **Provable from the code.** Every command, flag, and output below is what `cli.py` and its
> handlers actually do. If this doc and the code disagree, **the code wins.** lawnlord is CLI- and
> data-first; there is no interactive UI. Planned features live in the [ROADMAP](../ROADMAP.md).

Entry points: the `lawnlord` console script and `python -m lawnlord` (`__main__.py`), both call
`cli.main()`.

## Subcommands (`cli.py`)

| Command | Arg | Key flags | Writes | Read-only |
|---|---|---|---|---|
| `start` | `root` | `--force` | `intake/`, `lawnlord.toml`, `intake/README.md` | no |
| `report` | `root` | `--packet` | — (prints tables) | **yes** |
| `build` | `root` | `--packet`, `--corpus-dir`, `--force`, `--no-ocr`, `--gpu` | `corpus/` tree | no |
| `emit-boundaries` | `root` | `--packet` | `intake/bundle-boundaries.generated.json` (draft) | inspection only |
| `index` | `intake` | `--case-dir`, `--force`, `--no-ocr`, `--gpu` | `extracted/corpus/`, `lawnlord.duckdb` | no |
| `pack` | `intake` | `-o/--output` | `<caseNumber>.zip` (case.json + filings/) | no |
| `assemble` | `intake` | `-o/--output` | `<caseNumber>-master.pdf` + `.manifest.json` | no |
| `bundle` | `intake` | `-o/--output` | `<caseNumber>.bundle.zip` | no |
| `query` | — | `--case-dir`, `--text`, `--needs-review`, `--event`, `--phase`, `--party`, `--limit` | — (prints tables) | **yes** |

## Argument styles

- `start` / `report` / `build` / `emit-boundaries` resolve an **intake folder from `root`** (default
  cwd) via optional `lawnlord.toml`; `--packet` points at a specific ZIP or a folder of PDFs (errors
  if zero or multiple ZIPs and no `--packet`).
- `index` / `pack` / `assemble` / `bundle` take a **provider intake folder** (`[intake]`, default
  cwd); `query` reads `lawnlord.duckdb` under `--case-dir`.

## Outputs

- **corpus** (`build` / `index`): `archive.json`, `manifest.json`, and per
  `submission / document / section`: `source.pdf`, `toc.json`, and
  `sections/<NNN-slug>/{section.pdf, pages/page-NNN.pdf, text/page-NNN.txt, analysis/page-NNN.json}`.
- **index** (`index` / `bundle`): `lawnlord.duckdb` (schema v3 + BM25 FTS, LIKE fallback).
- **assemble**: a master PDF with a `FILING → IMAGE → DOC` outline, embedded attachments and
  annotations carried across, and a page-provenance `.manifest.json`; the summary reports
  text-lossless and visual-lossless round-trips.
- **bundle**: `case.json` + `filings/` + `case-master.pdf` + `pages/<stem>/pNNN.txt` +
  `lawnlord.duckdb` + `bundle-manifest.json` (all relative paths, self-contained).
- **query** results carry provenance: image title, source page, citation string.

## Not built (see the ROADMAP)

No interactive dashboard, no "ask what law applies," no strategy chat, no accept/decline UI, no
computed timeline. Those are planned in the [ROADMAP](../ROADMAP.md); they are not callable today.
