#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# capture-cosmos.sh — PRESERVE the cosmos (NVIDIA) machine state BEFORE any change.
#
# Run this FIRST, on cosmos, the moment you sit down. It is READ-ONLY: it captures
# evidence and changes nothing in the repo or the running system. It writes a
# timestamped folder OUTSIDE the repo plus a lossless git bundle of all local
# commits, so cosmic can reconstruct cosmos's git state exactly.
#
# Usage:
#     bash scripts/cosmos/capture-cosmos.sh
#     bash scripts/cosmos/capture-cosmos.sh --bench   # also run a short live benchmark
#
# Output:  ~/lawnlord-cosmos-capture-<UTC-timestamp>/   (+ a .tar.gz of it)
# Secrets: ANTHROPIC_API_KEY is REDACTED in captured .env copies. Do NOT commit
#          the capture folder; transport it out-of-band (see scripts/cosmos/README.md).
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail   # NOT -e: a missing tool must not abort the capture

REPO="$(cd "$(dirname "$0")/.." && cd .. && pwd)"   # scripts/cosmos -> repo root
cd "$REPO" || { echo "cannot cd to repo root"; exit 1; }

TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${HOME}/lawnlord-cosmos-capture-${TS}"
mkdir -p "$OUT"
echo ">> capturing cosmos state into: $OUT"

# Run a command, tee its output to a capture file, never abort on failure.
cap() { local f="$1"; shift; echo "## \$ $*" >>"$OUT/$f"; "$@" >>"$OUT/$f" 2>&1; echo >>"$OUT/$f"; }
redact() { sed -E 's/(ANTHROPIC_API_KEY|.*_KEY|.*_TOKEN|.*SECRET.*)=.*/\1=<REDACTED>/I'; }

# ── 1. Machine identity ───────────────────────────────────────────────────────
cap machine.txt hostname
cap machine.txt uname -a
cap machine.txt cat /etc/os-release
cap machine.txt bash -c 'grep -qi microsoft /proc/version && echo "WSL: yes" || echo "WSL: no (native Linux)"'
cap machine.txt date -u
cap machine.txt date

# ── 2. GPU / driver / CUDA ────────────────────────────────────────────────────
cap gpu.txt nvidia-smi
cap gpu.txt nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
cap gpu.txt bash -c 'which nvcc && nvcc --version'
cap gpu.txt bash -c 'ls -la /usr/local/cuda* 2>/dev/null'
cap gpu.txt bash -c 'ls -la /usr/local/lib/ollama 2>/dev/null; ls -la /usr/local/lib/ollama/cuda_* 2>/dev/null'

# ── 3. Inference runtime (Ollama / llama.cpp) ─────────────────────────────────
cap runtime.txt bash -c 'ollama --version'
cap runtime.txt bash -c 'ollama list'
cap runtime.txt bash -c 'ollama ps'
cap runtime.txt bash -c 'systemctl status ollama --no-pager 2>/dev/null | head -20'
cap runtime.txt bash -c 'env | grep -iE "ollama|cuda|llama|ggml" | redact || true'
cap runtime.txt bash -c 'find / -name "llama-server" -type f 2>/dev/null | head'
cap runtime.txt bash -c 'curl -fsS http://localhost:18082/health 2>/dev/null || echo "no llamacpp server on :18082"'
cap runtime.txt bash -c 'curl -fsS http://localhost:11434/api/tags 2>/dev/null | head -c 2000 || echo "no ollama on :11434"'

# ── 4. Python / lawnlord deps ─────────────────────────────────────────────────
cap deps.txt bash -c 'uv run python --version'
cap deps.txt bash -c 'uv run python -c "import duckdb,PIL;print(\"duckdb\",duckdb.__version__,\"pillow\",PIL.__version__)"'

# ── 5. Git state — the knowledge most at risk ─────────────────────────────────
cap git.txt git rev-parse --abbrev-ref HEAD
cap git.txt git status
cap git.txt git log --oneline -20 --decorate
cap git.txt git --no-pager diff --stat
cap git.txt git stash list
cap git.txt git remote -v
cap git.txt git branch -vv
cap git.txt git branch -r -vv
cap git.txt git fetch --all --tags
cap git.txt git reflog --date=iso -50
# Unpushed commits per local branch (vs its upstream), and anything not on origin/master:
cap git.txt bash -c 'for b in $(git for-each-ref --format="%(refname:short)" refs/heads); do echo "--- $b unpushed vs upstream ---"; git --no-pager log --oneline "@{upstream}..$b" 2>/dev/null || echo "(no upstream)"; done'
cap git.txt bash -c 'echo "--- commits reachable locally but NOT on origin/master ---"; git --no-pager log --oneline origin/master.. --all 2>/dev/null'

# FULL uncommitted diff (may contain real cosmos work) — separate file
git --no-pager diff > "$OUT/uncommitted.diff" 2>&1 || true
git --no-pager diff --cached > "$OUT/uncommitted-staged.diff" 2>&1 || true
git ls-files --others --exclude-standard > "$OUT/untracked-files.txt" 2>&1 || true

# LOSSLESS transport of every local commit + branch + tag (cosmic reconstructs from this):
git bundle create "$OUT/cosmos-all-refs.bundle" --all 2>&1 | tee -a "$OUT/git.txt" || true
cap git.txt git bundle verify "$OUT/cosmos-all-refs.bundle"

# ── 6. Machine-local config (gitignored) — copy with secrets redacted ─────────
for f in .env .env.local lawnlord.toml; do
  [ -f "$f" ] && { echo "## $f (secrets redacted)" >>"$OUT/local-config.txt"; redact <"$f" >>"$OUT/local-config.txt"; echo >>"$OUT/local-config.txt"; }
done
# Raw .env copies kept SEPARATELY (also redacted) so values survive transport:
for f in .env .env.local; do [ -f "$f" ] && redact <"$f" >"$OUT/$(echo "$f" | tr -d '.').redacted"; done
cap local-config.txt bash -c 'ls -la profiles/'
cp profiles/*.env "$OUT/" 2>/dev/null || true   # committed templates, for diffing against cosmic

# ── 7. Shell history (launch commands actually used) ──────────────────────────
for h in "$HOME/.bash_history" "$HOME/.zsh_history"; do
  [ -f "$h" ] && grep -hiE 'serve_vision|llama-server|llamacpp|transcribe|ollama|--backend|18082|nvidia|cuda|ngl|flash-attn|--parallel' "$h" 2>/dev/null
done | tail -120 > "$OUT/launch-commands.txt" 2>&1 || true

# ── 8. Benchmark logs already on disk ─────────────────────────────────────────
cap bench-existing.txt bash -c 'ls -la ~/ai 2>/dev/null; ls -la /mnt/*/ai 2>/dev/null; find . -name "*bench*" -o -name "sweep*" 2>/dev/null | grep -v node_modules'

# ── 9. Optional live benchmark (only with --bench, server must be up) ─────────
if [ "${1:-}" = "--bench" ]; then
  echo ">> running live benchmark (needs a vision server up)…"
  cap bench-live.txt bash -c 'uv run python scripts/cosmic/bench.py llamacpp http://localhost:18082 0 extracted/pages 8 2>/dev/null || echo "llamacpp bench skipped (no server / no pages)"'
fi

# ── package ───────────────────────────────────────────────────────────────────
tar -czf "${OUT}.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")" 2>/dev/null \
  && echo ">> bundle: ${OUT}.tar.gz"

cat <<EOF

>> DONE. Captured to:
     $OUT
     ${OUT}.tar.gz
>> Next (see scripts/cosmos/README.md):
   1. Eyeball $OUT/uncommitted.diff and $OUT/git.txt — is there real cosmos GPU work?
   2. Get ${OUT}.tar.gz back to cosmic (scp / USB / cloud — NOT a git commit; it has config).
   3. On cosmic: git fetch the bundle to inspect cosmos commits losslessly.
EOF
