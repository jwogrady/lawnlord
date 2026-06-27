# Multi-machine setup — cosmic (AMD) & cosmos (NVIDIA)

LawnLord is developed on two machines with different GPUs. The shared code is identical; only the
**runtime backend wiring** differs. This document records (1) how the two machines differ, (2) the
config strategy that keeps them from breaking each other, (3) what happened over 2026-06-24…26 and
why, and (4) a paste-ready checklist for capturing `cosmos` when next at that machine.

| | **cosmic** (work) | **cosmos** (home) |
|---|---|---|
| GPU | AMD Radeon RX 6900 XT (RDNA2/gfx1030, 16 GB) | NVIDIA *(confirm model at home)* |
| OS | Windows 11 + WSL2 (Ubuntu) | native Linux |
| Compute backend | **Vulkan** (ROCm unsupported on gfx1030) | CUDA |
| Where inference runs | **Windows host** (WSL offloads over HTTP) | **local** (Linux Ollama serves the GPU directly) |
| Ollama endpoint | `http://172.31.128.1:11434` (host gateway) | `http://localhost:11434` |
| Production vision path | `--backend llamacpp` → `scripts/cosmic/serve_vision.cmd 4 2048` (native 300 DPI, ~24 pg/min) | `--backend local` / `scripts/llamacpp_server.sh` *(confirm)* |
| Models present | `qwen2.5vl:7b` only | `qwen2.5vl:7b` + `minicpm-v:latest` *(confirm)* |
| Profile | [`profiles/cosmic-amd.env`](../../profiles/cosmic-amd.env) | [`profiles/cosmos-nvidia.env`](../../profiles/cosmos-nvidia.env) |
| Machine reference | [`development-machine.md`](development-machine.md) | *(to be written: `development-machine-cosmos.md`)* |

---

## Config strategy — shared code, isolated machine settings

The rule: **shared logic stays in tracked code; everything machine-specific lives in a gitignored
`.env`, seeded from a committed profile.** No GPU/vendor assumptions are baked into shared scripts.

```
profiles/cosmic-amd.env      ─┐  committed templates (NO secrets) — one per machine class
profiles/cosmos-nvidia.env    │  cosmic-amd · cosmos-nvidia · cpu-fallback
profiles/cpu-fallback.env    ─┘
            │  cp <profile> .env   (then append ANTHROPIC_API_KEY=...)
            ▼
        .env  (gitignored)  ── sourced by scripts/transcribe_local.sh & llamacpp_server.sh
            │                   (.env wins over the committed script defaults)
            ▼
   lawnlord transcribe …      ── --ollama-host falls back to $OLLAMA_HOST (cli.py)
```

**Activate a machine:**
```bash
cp profiles/cosmic-amd.env .env        # or cosmos-nvidia.env / cpu-fallback.env
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env   # secret stays only in gitignored .env
```

**What each layer owns:**
- **Tracked, shared:** `src/lawnlord/`, `scripts/transcribe_local.sh`, `scripts/llamacpp_server.sh`
  (these `source .env` and auto-probe `OLLAMA_HOSTS`), `scripts/cosmic/` (AMD/Vulkan Windows
  tooling), `.env.example`, `profiles/*.env`.
- **Gitignored, per-machine:** `.env` (active selection + secret), `lawnlord.toml`, case data.

Why this shape: a machine's quirks (which host serves Ollama, which models exist, how many workers)
never touch shared code, so pulling another machine's work can't silently repoint your GPU. The
committed profiles are documentation *and* the recovery seed if a `.env` is ever lost.

---

## What happened, 2026-06-24 … 06-26 (reconstruction)

Labeled **KNOWN** (from git) vs **LIKELY** (inferred) vs **UNCERTAIN** (needs cosmos).

- **KNOWN.** `master` @ `6c8ecf4` (Thu Jun 25 11:10 CDT) merged the shared llama.cpp vision backend
  (#142) and the local tuning scripts (#143). Those scripts originally carried the **cosmos**
  profile (localhost Ollama) as hardcoded defaults.
- **KNOWN.** cosmic pulled `master` Thu 15:13 (reflog fast-forward), receiving those cosmos-default
  scripts.
- **LIKELY (the break).** On cosmic, `localhost:11434` has no Ollama — its GPU inference lives on
  the **Windows host** (`172.31.128.1`). So the shared scripts pointed at nothing and cosmic's
  local-transcribe "broke." This is the most probable cause of Friday's lost day. (No
  cosmos-specific commit broke cosmic; the mechanism was the *shared* scripts' cosmos default.)
- **KNOWN (the fix).** Fri Jun 26 19:31 CDT, commit `a10bf8e` on branch `chore/cosmic` added the
  **`.env` override + `OLLAMA_HOSTS` auto-probe** so each machine self-selects. That commit also
  accidentally tracked `scratchpad_transcribe.log` (since removed + gitignored).
- **KNOWN.** No secrets or `.env` were ever committed; `.gitignore` covers them.
- **UNCERTAIN.** Whether Thursday-night's **cosmos** NVIDIA GPU work was committed — no NVIDIA-only
  commit is visible in cosmic's local history. Two **remote-only** branches exist and were **not**
  inspected: `docs/review-notes`, `qc/hardening-pass`. Resolve both at home (checklist below).

**Net:** the dual-machine pattern now lives in shared code; this doc + the profiles make it durable.

---

## cosmos check-in checklist (run at home)

Capture everything **before** changing anything. Save the output somewhere outside the repo.

```bash
cd ~/workspace/lawnlord        # adjust if the cosmos path differs

# 1. Repo state — is the Thursday GPU work committed?
git status
git branch --show-current
git log --oneline -12
git --no-pager diff --stat
git --no-pager diff                 # full uncommitted diff — SAVE THIS if non-empty
git stash list
git fetch --all                     # then inspect the two unknown remote branches:
git --no-pager log --oneline -5 origin/docs/review-notes origin/qc/hardening-pass

# 2. Machine-local config (gitignored — the knowledge most at risk)
cat .env 2>/dev/null
cat lawnlord.toml 2>/dev/null

# 3. GPU / runtime / model
nvidia-smi
ollama --version ; ollama ps ; ollama list
uv run python --version
uv run python -c "import duckdb,PIL;print('duckdb',duckdb.__version__,'pillow',PIL.__version__)"

# 4. Benchmark — confirm GPU acceleration is actually live (not CPU fallback)
./scripts/transcribe_local.sh       # or the cosmos llamacpp_server.sh path
#   watch: nvidia-smi shows the python/ollama process on the GPU; tok/s is GPU-class, not ~8.
```

**Then, to preserve cosmos durably (mirror what we did for cosmic):**
1. If `git status`/`diff` shows **uncommitted GPU work**, decide per-file: shared logic → commit to
   a branch; machine-specific values → fold into `profiles/cosmos-nvidia.env` (it currently holds
   *placeholder* defaults marked `TODO(verify-at-home)`).
2. Copy the real cosmos `.env` values (minus secrets) into `profiles/cosmos-nvidia.env`.
3. Write `docs/reference/development-machine-cosmos.md` (mirror of `development-machine.md`): GPU,
   driver/CUDA, Ollama/llama.cpp versions, model, commands, benchmark, verification checklist.
4. Do **not** commit `.env`, `lawnlord.toml`, or any case-page renders.

---

*See also:* [`development-machine.md`](development-machine.md) (cosmic spec) ·
[`../performance/native-300dpi-vulkan-benchmark.md`](../performance/native-300dpi-vulkan-benchmark.md) ·
[`../performance/cosmic-backend-comparison.md`](../performance/cosmic-backend-comparison.md) ·
[`../../profiles/`](../../profiles/) · [`../../scripts/cosmic/`](../../scripts/cosmic/)
