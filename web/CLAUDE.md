Default to using Bun instead of Node.js.

- `bun <file>` / `bun run <script>` (not `node` / `npm run`)
- `bun install` (not npm/yarn/pnpm)
- `Bun.serve()` supports routes, HTML imports, WebSockets, HMR — don't use express/vite.
- `Bun.$\`cmd\`` for shelling out (not execa); `Bun.file` over node:fs reads.
- Bun auto-loads `.env`.

## This app

The Actual-lens viewer. It reads the case's DuckDB **mirror** through the Python
CLI (`uv run lawnlord export-actual`), never by re-parsing the zip, and serves
the filed PDFs + captured Odyssey `pages/*.html` from the intake dir.

Run it against a case built by `lawnlord import`:

```sh
cd web && CASE_DIR=/path/to/case bun dev
```

`CASE_DIR` holds `lawnlord.duckdb` and `intake/<stem>/` (with `files/` + `pages/`).
The lens ends at the image — no extracted text or analysis (that's the Exploded
lens, a later issue).
