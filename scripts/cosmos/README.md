# `scripts/cosmos/` — NVIDIA (cosmos) preservation & recovery

Tooling to **preserve the `cosmos` home workstation (NVIDIA/CUDA) before changing anything**, then
fold its real configuration into the cleaned `cosmic`-reference architecture. `cosmos` has **not**
been inspected yet — everything about its NVIDIA setup is currently UNVERIFIED
(`profiles/cosmos-nvidia.env` is a placeholder template, `scripts/llamacpp_server.sh` is the
expected-but-unvalidated CUDA launcher).

> **Golden rule:** capture first, change nothing until the capture is safe off-machine.

## Step 1 — Capture (run on cosmos, first thing)

```bash
cd ~/workspace/lawnlord        # adjust if the cosmos clone lives elsewhere
git fetch --all --tags         # pick up cosmic's preserved master + the rollback tag
bash scripts/cosmos/capture-cosmos.sh          # read-only; writes ~/lawnlord-cosmos-capture-<ts>/
#   add --bench to also time a live server:    bash scripts/cosmos/capture-cosmos.sh --bench
```

This captures: hostname, OS/WSL, `nvidia-smi`, CUDA paths, Ollama/llama.cpp runtime, model list,
**full git state** (branch, status, unpushed commits, reflog, stash, untracked), a **lossless
`git bundle` of all refs**, machine-local `.env`/`lawnlord.toml` **with secrets redacted**, shell
launch history, and any existing benchmark logs. Output folder + `.tar.gz`.

## Step 2 — Triage on cosmos (before any cleanup there)

Open the capture and answer:
- `git.txt` → are there **unpushed commits** or commits not on `origin/master`?
- `uncommitted.diff` → is there **real uncommitted NVIDIA work**?
- `local-config.txt` → what are cosmos's real `.env` values (host, models, workers)?
- `launch-commands.txt` → what server command actually produced good results?

If there is uncommitted work you want to keep, **commit it to a branch on cosmos** before anything
else (do not let it sit only in the working tree):
```bash
git switch -c chore/cosmos-capture-<ts>
git add -A && git commit -m "wip: cosmos NVIDIA state captured <ts> (pre-cleanup snapshot)"
git push origin chore/cosmos-capture-<ts>      # fast-forward to a NEW branch; no history rewrite
```

## Step 3 — Get evidence back to cosmic

Two channels, kept separate:

| What | How | Why |
|---|---|---|
| Commits/branches | `git push origin chore/cosmos-capture-<ts>` **or** transport `cosmos-all-refs.bundle` | git is the source of truth for code |
| The capture `.tar.gz` (configs, logs, diffs) | scp / USB / cloud drive — **never** `git add` it | it contains machine config; keep it out of the repo |

On cosmic, inspect the bundle losslessly without merging:
```bash
git fetch ~/transferred/cosmos-all-refs.bundle '*:refs/cosmos/*'   # cosmos refs under refs/cosmos/*
git log --oneline --all --decorate | grep cosmos
git range-diff origin/master...refs/cosmos/heads/<branch>          # see exactly what cosmos changed
```

## Step 4 — Merge NVIDIA into the cleaned architecture

Target model (already accepted): one repo, one `master`, **no permanent GPU branches**; machine
differences live only in profiles + the per-backend launcher. So fold cosmos in as **config + a
launcher**, never as a parallel branch. See the merge plan in this prompt's report and
[`../../docs/reference/multi-machine-setup.md`](../../docs/reference/multi-machine-setup.md).

Concretely:
1. **Shared** (same on both): anything in `src/lawnlord/`, the `Transcriber` contract,
   `scripts/cosmic/bench.py` — reuse as-is.
2. **`cosmos-nvidia` machine-specific:** replace the placeholders in `profiles/cosmos-nvidia.env`
   with the captured real values (host, models, workers, lib path). Validate
   `scripts/llamacpp_server.sh` against `launch-commands.txt`; lift the UNVERIFIED banner once it runs.
3. **Machine-local (never committed):** the real `.env`, `lawnlord.toml`, model blobs, CUDA libs.
4. **Verify both still work:** cosmic via [`cosmic-amd-runbook.md`](../../docs/reference/cosmic-amd-runbook.md);
   cosmos via the same `--backend llamacpp` path against its CUDA server. Neither machine's defaults
   may leak into the other (AMD/Vulkan ⟂ NVIDIA/CUDA).
