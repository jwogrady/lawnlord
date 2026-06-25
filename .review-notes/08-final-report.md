# Final Report — Project Audit

**Date:** 2026-06-25
**Reviewed by:** jwogrady
**Scope:** Whole-project audit of `lawnlord` v0.4.0 (branch `feat/llamacpp-gpu-vision`), synthesized from seven specialist reviews (00–07).

---

## 1. Executive Summary

`lawnlord` is a genuinely well-engineered local-first legal case-understanding engine whose **core is stronger than its surface**. The architecture is textbook-clean (a unidirectional zip → DuckDB → export → read-only viewer pipeline), the code is disciplined single-author work that type-checks clean and carries WHY-not-WHAT comments and zero TODO debt, and the project's flagship invariant — *mirror the court record immutably, add everything else additively* — is **enforced by construction** at the database level (no `UPDATE` anywhere, append-only `page_text`, content-hash IDs, manifest-derived timestamps, byte-identical re-import). Both promised lenses (Actual + Exploded) work end-to-end on the real 255-page case today. There are **no shipping blockers for the author's own alpha use** and **no critical security holes** for its localhost, single-user threat model.

The weaknesses cluster into one theme: **the project sells "provenance you can trust," but several trust-critical pieces are assumed rather than proven.** The "self-verifying per-file sha256" claim is unimplemented (the manifest's hashes and source URLs are read by nothing); there is no acceptance test that the real court zip round-trips byte-identically despite the fixture sitting in the repo; the schema-version check is a no-op so a stale DB silently misreports its own provenance; and the three docs the project *designates* as authoritative code summaries are materially false (wrong schema version, wrong command set, a phantom `curation.py`). Operationally it is unsupportable by anyone but its author: the README's headline install (`uv add lawnlord`) is fictional, there is no documented build runbook, no logging/health-check, and the viewer hangs forever on any `/api/case` failure. **None of these are hard to fix** — they are the gap between a strong engine and a trustworthy, handoff-ready product.

---

## 2. Scores by Dimension

| Dimension | Score | Source |
|---|---|---|
| Structure & clarity | 8 | Agent 00 |
| Documentation / onboarding | 5 | Agent 01 |
| Architecture / sustainability | 8 | Agent 02 |
| Code quality / maintainability | 8 | Agent 03 |
| Testing / reliability | 7 | Agent 04 |
| Security / configuration | 7 | Agent 05 |
| Product readiness | 6 | Agent 06 |
| **Provenance & invariant integrity** (custom) | 7 | Agent 07 |

## 3. Overall Health Score

**7 / 10 — strong foundation, trust-surface and operations need polish.**

Risk-weighted, not a flat average: architecture, code, and the immutability/determinism invariants (the expensive-to-get-right core) are genuinely strong (8/8/strong-7) and pull the score up; documentation (5) and product operations (6) pull it down, and they matter *more than usual here* because this specific project's entire value proposition is verifiable trust — a 5 on doc-truth and an unimplemented self-verification step are not cosmetic for a provenance engine. The core is a 9; the trust/ops surface is a 5; the blend lands at a defensible 7.

---

## 4. Critical Risks

Severity calibrated for a **local-first, single-user** tool. None block the author's own use; all block a confident handoff or a "provenance you can trust" claim.

- **[High — to the *claim*] "Self-verifying via per-file sha256" is unimplemented.** The intake manifest carries `sha256`/`url`/`bytes` per filed PDF; nothing reads it. `ingest` computes a *fresh* hash for the id but never compares it to the manifest's declared hash, and the stored `images.sha256_hash` / `pages.page_image_sha256` are written once and never re-verified. The zip is *trusted*, not *verified* (`reader.py:46-109`, `ingest.py:156`). For a provenance engine this is the single biggest promise-vs-code gap.
- **[High — trust] Documentation truth-drift in the authoritative code-summary docs.** `architecture.md`/`schema.md` claim `SCHEMA_VERSION = 6` (code is 11), `start` is the only subcommand (there are 10), and `from_intake` is a stub (it is implemented); `ROADMAP.md:42` cites a phantom `curation.py`/`ALLOWED_CURATED_FIELDS` as the enforcement point for governing invariant #2; the README test badge says 27 (actual: 94). The project's own "code wins, fix the doc" rule is violated in the files meant to enforce it.
- **[Medium] No acceptance test against the real intake zip.** 94 tests pass at 83% coverage, but every test uses a synthetic 1–2-page fixture. The central round-trip invariant (real court zip → ingest → explode → byte-identical re-import) is *never* exercised, despite the 17 MB fixture sitting in `intake/odyssey-250914566/`.
- **[Medium] Schema-version check is a no-op → silent stale-DB provenance defect.** `apply_schema` (`db.py:231-237`) writes the version only when the table is empty and never compares the stored value to `SCHEMA_VERSION`; a v9 DB opened by v11 code keeps `version=9` and silently ignores changed columns. The tree literally contains `lawnlord.duckdb.v9.bak` — the operator hit exactly this.
- **[Medium] Viewer hangs forever on any primary-lens failure.** `load()` has no try/catch (`app.ts:136-139`) and `/api/case` + `/api/exploded` have no server-side catch (`index.ts:63-81`), while `/api/metrics` + `/api/regions` do. A missing/locked DB or broken `uv` env leaves a permanent "Loading…" with no message.
- **[Medium] Flagship feature renders nothing, with no signal.** The #129 on-image highlight overlay is fully wired but `page_regions` has 0 rows — the `lawnlord regions` pipeline step was never run on the corpus and is absent from every documented sequence; the overlay silently no-ops.
- **[Low-Med] Cloud transcriber has no truncation safeguard.** The default, highest-trust tier does a bare `json.loads` (`transcribe.py:126`) with no `stop_reason` check; a token-ceiling-truncated response raises an unhandled `JSONDecodeError`. Both local and llama.cpp tiers guard this (force fidelity 0.0).

---

## 5. Architectural Debt

- **Schema versioning is decorative** (`db.py:231-237`) — no read, no compare, no migration path, silent stale-DB failure. *(highest-value architectural fix; see Critical Risks)*
- **Mirror immutability is structural only at the export boundary.** Past `ingest.py` the "additive only" rule is convention — every write command opens the same read-write handle, and nothing stops a future `analysis` module from `UPDATE`-ing a mirror table. Latent, not yet violated, but the engine doesn't enforce its headline invariant past one module.
- **Per-request `uv run` subprocess model** (`index.ts:63-124`) — every `/api/*` cold-starts Python + DuckDB + a whole-case export, no caching/pooling. Measured ~0.27–0.37s warm, a non-issue at one user / one case / 255 pages, but a hard scalability ceiling and the reason a broken `uv` env fails every request.
- **DuckDB single-writer lock** — a `transcribe`/`explode` run concurrent with the viewer (or a second write) will lock; untested, undocumented, no strategy.
- **`cli._main` is a 250-line, complexity-34 dispatch chain** (`cli.py:332-583`) — readable but untestable as one unit and the obvious refactor target (dispatch dict → per-command handlers, which also unlocks unit-testing each subcommand).
- **Stale module narration** — `workspace.py:6-8` still says the reader "lands on the next branch" over fully-implemented code; `OUTPUT_SUBDIRS` lists 5 dirs no current code writes (pre-pivot scaffold).

---

## 6. Testing Gaps

- **No round-trip acceptance test on the real zip** (the #1 highest-value test to add — verifies the central invariant end-to-end).
- **Untested truncation path on the default cloud tier** (`transcribe.py:126`) — no test exercises a truncated cloud response.
- **`cli.py` at 57% / `__main__.py` at 0%** — the user-facing dispatch (`_main` lines 488-583) is largely uncovered; no `test_ingest.py`, no `test_workspace.py` (from_intake body mostly uncovered).
- **No crash-recovery / resume test** — "durable mid-run" rests entirely on DuckDB per-statement autocommit (no explicit transactions anywhere in `src/`); no kill-mid-run-then-resume assertion.
- **DuckDB single-writer lock behavior untested** (viewer + transcribe collision).
- **No CI runs the 94 tests on a change** — a regression ships silently.
- *Well-covered already (credit where due):* the fragile `_parse_local_output` salvage, retry/backoff classification, concurrent page ordering, partial-failure accumulator, append-only `force` rev guard, and server-down degradation all have direct assertions.

---

## 7. Security Findings

Threat model: localhost, single-user, operator's own legal case. **No hardcoded secrets, no reachable command injection (all `Bun.$` shell-outs use auto-escaping tagged-template interpolation), correct zip-slip protection, key is env-only and never logged.**

- **[Medium-Low] Static handlers bypass `safeJoin`.** `serveFromIntake` (`/files/*`, `/pages/*`) and `/png/*` (`index.ts:50-55,140-143`) confine with only a substring `.includes("..")` check — no symlink resolution, no absolute-path rejection — while the robust, symlink-resolving `safeJoin` exists three files away in `download.ts` and is used correctly by every download path. Exploit precondition: an attacker-planted symlink inside the case dir.
- **[Medium → effectively Low] Insecure default bind.** `Bun.serve` sets only `port`, so it binds `0.0.0.0` (LAN/VPN-reachable) with no auth and no CORS, while serving sensitive legal PDFs + transcriptions. Docs promise "local, single-user." One-line fix: `hostname: "127.0.0.1"`.
- **[Low] No automated dependency CVE audit.** Floors pinned low with no upper bound (`pillow>=10.0`, `pypdfium2>=4.30` parse untrusted court PDFs/images); no `pip-audit`/Dependabot (no CI). No known-exploited CVE found in this pass.

---

## 8. Product Readiness

- **Delivered:** both lenses work end-to-end on the real case (1 case, 3 parties, 29 events, 22 docs, 255 pages, 404 `page_text` rows); polished three-lens UI with breadcrumb drill-down, comparison grid, confidence gauges, flagged-page worklist, divergence highlighting; thoughtful loading/empty states; genuinely good backend graceful degradation (Ollama/llama.cpp/API down → clear skip reason, never crashes).
- **Gaps:** flagship overlay renders nothing (regions step never run, no signal); no top-level viewer error/timeout state; fictional `uv add lawnlord` install with no real `import→explode→transcribe→regions→serve` runbook; zero logging/health-check; accessibility is a near-blank slate (no `:focus`/`aria-*`/`role=` anywhere, one borderline-contrast muted color).
- **Performance:** a non-issue at the stated scale (measured; exploded payload ~1 MB fetched once and cached).

---

## 9. Documentation Gaps

- The three authoritative "code summary" docs (`architecture.md`, `schema.md`, `ux.md`) describe the 0.4.0 teardown snapshot, not the shipped code (wrong schema version, wrong command set, "stub" claims for shipped code, 4 phantom tables, the entire web app absent).
- No formal CLI/API/web-route spec — the export JSON contracts live only in `export.py` + argparse `help=` strings; a new dev must read `cli.py` + `export.py` + `web/index.ts`.
- ADRs 0001–0003 are marked `Proposed` despite the decisions being shipped (Ollama + llama.cpp backends).
- No root `CLAUDE.md`/`AGENTS.md` (engineering invariants live in `contributing.md`, well-written but not where an agent looks first).
- *Strong, accurate, keep-as-is:* `CHANGELOG.md` (exemplary, current), `contributing.md`, the problem statements, ADRs 0004–0009, `web/CLAUDE.md`.

---

## 10. Performance Baselines

| Operation | Measured | Note |
|---|---|---|
| `export-actual` | ~0.37s, 14 KB | per request |
| `export-exploded` (whole case) | ~0.27–0.28s warm, ~1.0 MB | fetched once/session, client-cached |
| `uv run lawnlord --help` (bare) | ~0.17–0.19s | subprocess+import dominates; DuckDB open is cheap |
| Test suite | 94 passed in 4.82s | — |
| Coverage | 83% (1451 stmts, 243 missed) | `cli.py` 57%, `__main__.py` 0% |

No defined performance targets in the docs; actuals are comfortably fine for the single-user scope. The cold-Python-per-request model is a structural ceiling that does not bite at this scale.

---

## 11. Observability & Ops

- **Zero `logging` anywhere in `src/`** — all output is a human-aimed Rich console singleton; no levels, timestamps, structured context, or log file. A failed overnight transcription run yields a bare count + page-ID list, no per-page reason/model/exception.
- **No health/readiness check** on the `uv`/Ollama/llama.cpp dependencies the web tier shells into.
- **No CI** — tests, lint, type-check, and dep-audit are all manual.
- **No stale-DB detector** despite the regenerate-by-hand workflow the `.bak` files prove the operator uses.

---

## 12. Top 20 Actions

Ranked by impact × urgency ÷ effort. Effort S/M/L, Impact S/M/H.

1. **Verify manifest per-file sha256 on import** — compare ingest's computed hash to the manifest's declared hash, fail loud on mismatch. (Effort: M, Impact: H, Owner: 07) — *closes the headline provenance gap.*
2. **Add a round-trip acceptance test on the real `intake/odyssey-250914566/` zip** (ingest → explode → re-import byte-identical). (Effort: M, Impact: H, Owner: 04)
3. **Make `apply_schema` read & compare `schema_meta.version`** — warn/refuse on mismatch, point the operator at regenerate. (Effort: S, Impact: H, Owner: 02/07)
4. **Fix the three code-summary docs** (`architecture.md`, `schema.md`, `ux.md`) to match v11 / 10 subcommands / implemented `from_intake` / real tables / the web app. (Effort: M, Impact: H, Owner: 01)
5. **Fix the README install + add a real runbook** — replace fictional `uv add lawnlord`, document `import→explode→transcribe→regions→serve`. (Effort: S, Impact: H, Owner: 06)
6. **Add try/catch to `/api/case` + `/api/exploded`** and a top-level catch + error state in `load()` — no more permanent "Loading…". (Effort: S, Impact: H, Owner: 02/06)
7. **Set up CI** (GitHub Actions: run the 94 tests + ruff + tsc + pip-audit on every push). (Effort: M, Impact: H, Owner: 00/03)
8. **Guard the cloud transcriber against truncation** — check `stop_reason`, force fidelity 0.0 on `max_tokens`, match local/llamacpp. (Effort: S, Impact: M, Owner: 04)
9. **Run `lawnlord regions` on the corpus** (or signal "regions not captured") so the flagship overlay isn't silently blank. (Effort: S, Impact: M, Owner: 06)
10. **Reuse `safeJoin` in the static handlers** (`index.ts:50-55,140-143`) instead of `.includes("..")`. (Effort: S, Impact: M, Owner: 05)
11. **Bind the viewer to `127.0.0.1`** (`index.ts:57`). (Effort: S, Impact: M, Owner: 05)
12. **Add `[tool.ruff] line-length = 99` + `per-file-ignores {"__init__.py" = ["F401"]}`** — collapses 65 lint findings to 2 real ones. (Effort: S, Impact: M, Owner: 03)
13. **Persist & export source-URL provenance** — add the manifest per-file `url` to `images`, select `source_url`/`last_refreshed` into the Actual export. (Effort: M, Impact: M, Owner: 07)
14. **Refactor `cli._main` into a command→handler dispatch dict** — kills the C901-34 hotspot and makes each subcommand unit-testable. (Effort: M, Impact: M, Owner: 03)
15. **Introduce structured `logging`** with a per-run log file capturing per-page failure reason/model/exception. (Effort: M, Impact: M, Owner: 04/06)
16. **Add mypy config + run in CI** (no type-checker today; web `tsc` is already clean — enforce both). (Effort: M, Impact: M, Owner: 03)
17. **Update ADRs 0001–0003 to `Accepted`** to match shipped code. (Effort: S, Impact: S, Owner: 01)
18. **Add tests for `ingest`, `workspace.from_intake`, and `cli` dispatch** (raise `cli.py` off 57%). (Effort: M, Impact: M, Owner: 04)
19. **Document/handle the DuckDB single-writer lock** (viewer + transcribe collision) — at minimum a clear error, ideally a lock check. (Effort: M, Impact: S, Owner: 02/04)
20. **Accessibility pass** — visible focus states, `aria-*`/`role=` on lens controls, fix the borderline `--muted`/`--panel` contrast. (Effort: M, Impact: S, Owner: 06)

---

## 13. Quick Wins

Low effort, immediate value (subset of above, all Effort S):

- `[tool.ruff]` config → 65 findings collapse to 2 (#12).
- Remove the 2 real lint findings (`tests/test_transcribe.py:498,526`).
- Bind to `127.0.0.1` (#11) and reuse `safeJoin` (#10) — two-line security hardening.
- `try/catch` on the two primary API routes + viewer `load()` (#6) — eliminates the permanent-"Loading…" failure mode.
- Schema-version compare/warn (#3) — small change, closes a real provenance defect.
- Fix the README install line + the "27 tests" badge (#5) — restores doc trust cheaply.
- Flip ADRs 0001–0003 to Accepted (#17).

---

## 14. Recommendations

**Strategic theme: close the trust gap before the feature gap.** This project's differentiator is *verifiable* provenance, and right now several trust-critical pieces are assumed rather than proven. Before building the next lens or the corpus-as-MCP capstone, spend one focused pass making the existing promises true: verify the manifest checksums on import (#1), add the real-zip round-trip test (#2), make the schema version self-report honestly (#3), and re-truth the three code-summary docs (#4). These four turn "an immutable base you assume is intact" into "an immutable base you can prove is intact" — which is the whole pitch.

**Operationalize for a second user.** The engine is ready; the operations are not. A real runbook (#5), CI (#7), top-level error handling (#6), and basic logging (#15) are the difference between "works for its author" and "another person can stand it up and debug it." Track these as a v0.5.0 "hardening" milestone.

**Adopt the cheap guardrails now.** Ruff config + CI + mypy (#7, #12, #16) cost a day and permanently prevent the silent-regression risk that today's clean-but-unenforced code is one careless commit away from. The code is already near-clean; lock it in.

**Keep doing:** the additive-layers discipline, content-hash determinism, the read-only CLI/web boundary, WHY-not-WHAT comments, the exemplary CHANGELOG, and the canonical-vs-derived visual separation are all genuinely strong — they are why the core scores 8s. Protect those invariants as the codebase grows past one author.

---

*Reviewed by jwogrady. Snapshot audit of `lawnlord` v0.4.0 at branch `feat/llamacpp-gpu-vision`, 2026-06-25.*
