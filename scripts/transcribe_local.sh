#!/usr/bin/env bash
# Local-GPU, model-major page transcription for lawnlord (the Ollama --backend
# local path: downscales to ~1500px, vision encode on CPU).
#
# NOTE (cosmic/AMD): this is the SLOW path (~100 min for the 255-page case). For
# the ~10-min native-300-DPI job, use the Vulkan vision server instead:
#     scripts/cosmic/serve_vision.cmd 4 2048   (Windows)  +  scripts/cosmic/transcribe_vision.sh
# See docs/performance/cosmic-backend-comparison.md.
#
# MODEL-MAJOR: sweep all pages with ONE model, then the next. Each model loads
# into VRAM once and — because requests come back-to-back — stays resident for
# its whole sweep, instead of the default `--backend local` pass that interleaves
# all models per page and thrashes a 10 GB card with reloads. Pair with the
# server tuning in scripts/ollama_tuning.md (NUM_PARALLEL=2, MAX_LOADED_MODELS=1,
# flash attention, q8 KV cache) so the two concurrent --workers actually overlap
# on the GPU and only one model is resident at a time.
#
# Per-model handling lives in transcribe.py (_LOCAL_TUNING): high-DPI page
# renders overflow Ollama's default 4096-token context, granite's encoder is
# capped, and minicpm's runaway output is salvaged. See that table for details.
#
# Resume is automatic: transcribe skips any (page, model) variation already in
# the DB, so re-running is safe and additive.
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, regardless of where it's invoked from

# --- per-machine config (separated from code) ---------------------------------
# What is committed below is the COSMOS profile (home box: a local Linux Ollama
# serving the RTX 3080 directly). Override any knob per-machine in a gitignored
# .env at the repo root — see .env.example. .env wins; these are the defaults.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

LAWNLORD="${LAWNLORD_BIN:-.venv/bin/lawnlord}"

# Sequential corpus (model-major), space-separated. Cosmos has both installed:
#   qwen2.5vl:7b     — primary, high fidelity (~0.98).
#   minicpm-v:latest — low-confidence comparison reading (output salvaged,
#                      fidelity flagged 0.0 so divergence metrics down-weight it).
# Excluded: granite3.2-vision:2b — 16,384-token ctx vs a ~18,349-token image;
#   only fits at <=384px, illegible for dense court pages. Not a tuning issue.
# A machine missing a model overrides LAWNLORD_MODELS in .env.
read -r -a MODELS <<< "${LAWNLORD_MODELS:-qwen2.5vl:7b minicpm-v:latest}"

# Ollama runs the vision projector on CPU (--no-mmproj-offload), so per-page cost
# is the CPU image-encode. --workers=1 because the server runs NUM_PARALLEL=1
# (vision serializes anyway). Override per-machine via LAWNLORD_WORKERS.
WORKERS="${LAWNLORD_WORKERS:-1}"

# Ollama endpoint. If OLLAMA_HOST is set it wins (manual override). Otherwise
# probe OLLAMA_HOSTS (space-separated candidates) and use the first that answers
# /api/tags. Cosmos serves locally; other machines add their host in .env, e.g.
#   OLLAMA_HOSTS="http://172.31.128.1:11434 http://localhost:11434"   # WSL→Windows
read -r -a PROFILES <<< "${OLLAMA_HOSTS:-http://localhost:11434}"

ollama_up() { curl -fsS -m 4 "$1/api/tags" >/dev/null 2>&1; }

if [ -n "${OLLAMA_HOST:-}" ]; then
  ollama_up "$OLLAMA_HOST" || { echo "OLLAMA_HOST=$OLLAMA_HOST is not reachable." >&2; exit 1; }
  echo ">> using OLLAMA_HOST override: $OLLAMA_HOST"
else
  OLLAMA_HOST=""
  for cand in "${PROFILES[@]}"; do
    if ollama_up "$cand"; then OLLAMA_HOST="$cand"; echo ">> auto-detected Ollama: $cand"; break; fi
    echo ">> not reachable: $cand"
  done
  [ -n "$OLLAMA_HOST" ] || { echo "No Ollama server reachable on any known profile." >&2; exit 1; }
fi

HOST_ARGS=(--ollama-host "$OLLAMA_HOST")

# Stop any transcribe already holding the DB lock (an earlier/abandoned run).
if pgrep -f "lawnlord transcribe" >/dev/null; then
  echo ">> stopping running transcribe..."
  pkill -f "lawnlord transcribe" || true
  sleep 2
fi

for model in "${MODELS[@]}"; do
  echo
  echo "============================================================"
  echo ">> $model   (--workers $WORKERS${OLLAMA_HOST:+, host $OLLAMA_HOST})"
  echo "============================================================"
  "$LAWNLORD" transcribe --backend local --model "$model" --workers "$WORKERS" "${HOST_ARGS[@]}"
done

echo
echo ">> done. all models swept."
