Default to using Bun instead of Node.js.

- `bun <file>` / `bun run <script>` (not `node` / `npm run`)
- `bun install` (not npm/yarn/pnpm)
- `Bun.serve()` supports routes, HTML imports, WebSockets, HMR — don't use express/vite.
- `Bun.$\`cmd\`` for shelling out (not execa); `Bun.file` over node:fs reads.
- Bun auto-loads `.env`.

## This app

The case viewer, a lens switcher over the same immutable record. It reads the
case **only** through the Python CLI's read-only JSON exports (`uv run lawnlord
export-actual` / `export-exploded`), never by re-parsing the zip, and serves the
filed PDFs, captured Odyssey `pages/*.html`, and page PNGs from disk.

Lenses:

- **Actual** — the court's record from the DuckDB **mirror**: register of
  actions, parties, each filing as its native PDF. Ends at the image.
- **Odyssey snapshot** — the captured `pages/*.html`, verbatim, for parity.
- **Exploded** — the fully-exploded QA comparison viewer (#125). Drill down
  **case → filing → image → document → page** by breadcrumb; each page image
  sits beside a comparison grid with one column per transcription variation (the
  PDF text layer plus each vision model). The canonical record is styled apart
  from derived AI readings, and missing/empty readings show explicitly. Tokens
  that diverge from the canonical anchor are highlighted and low-confidence
  readings flagged (⚑), both from the export's `divergence`/`flagged` fields. It
  only renders what the exports carry — it never derives, re-diffs, or re-scores.

Run it against a case built by `lawnlord import`:

```sh
cd web && CASE_DIR=/path/to/case bun dev
```

`CASE_DIR` holds `lawnlord.duckdb` and `intake/<stem>/` (with `files/` + `pages/`).
