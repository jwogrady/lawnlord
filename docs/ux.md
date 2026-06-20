# User-facing behavior (developer code summary)

> **Provable from the code.** Every command, flag, and output below is what `cli.py` and its
> handlers actually do. If this doc and the code disagree, **the code wins.** lawnlord is CLI- and
> data-first; there is no interactive UI yet. Planned features live in the [ROADMAP](../ROADMAP.md).

Entry points: the `lawnlord` console script and `python -m lawnlord` (`__main__.py`), both call
`cli.main()`.

> **Alpha rebuild.** After the pivot to the zip standard, the only command that runs today is
> `start`. The zip → DuckDB build and the Actual / Exploded views are the next branches
> ([ROADMAP](../ROADMAP.md)).

## Subcommands (`cli.py`)

| Command | Arg | Key flags | Writes | Read-only |
|---|---|---|---|---|
| `start` | `root` | `--force` | `intake/`, `lawnlord.toml`, `intake/README.md` | no |

`start` scaffolds the intake folder under `root` (default cwd): the `intake/` dir, a starter
`lawnlord.toml`, and an intake README explaining that the deterministic zip is the single source of
truth. Existing files are left alone unless `--force`.

## Intake-root resolution (`cli._resolve_intake`, `cli._intake_root`)

So case data can live in a separate repo or local in the project, an intake folder is resolved as an
explicit path (used as-is) **or** a bare name under the configured intake root, in this order:

1. `LAWNLORD_INTAKE` env var,
2. `lawnlord.toml`'s `[lawnlord] intake` (absolute or relative to the project),
3. `./intake` (the in-project default).

The intake itself is the deterministic zip (`<case>.zip`); `intake.resolve_packet` locates the single
`*.zip` in the intake dir.

## Not built yet (see the ROADMAP)

No zip → DuckDB build, no query, no Actual/Exploded views, no analysis or accept/decline UI. Those are
the near-term work in the [ROADMAP](../ROADMAP.md); they are not callable today.
