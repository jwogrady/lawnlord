#!/usr/bin/env bash
# Local-GPU, model-major page transcription for lawnlord.
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

LAWNLORD=.venv/bin/lawnlord
# Sequential corpus (model-major). Verified on the 300-DPI renders:
#   qwen2.5vl:7b     — primary, high fidelity (~0.98).
#   minicpm-v:latest — low-confidence comparison reading (output salvaged,
#                      fidelity flagged 0.0 so divergence metrics down-weight it).
# Excluded:
#   granite3.2-vision:2b — architecturally unfit: 16,384-token context vs a
#                          ~18,349-token image; only fits at <=384px, which is
#                          illegible for dense court pages. Not a tuning issue.
MODELS=(qwen2.5vl:7b minicpm-v:latest)

# Ollama runs the vision projector on CPU (--no-mmproj-offload), so per-page cost
# is the CPU image-encode, ~linear in image tokens. qwen reads at 1500 px by
# default (transcribe.py _LOCAL_TUNING): ~30 s/page, printed text identical to
# 300 DPI. This is the fast MAIN pass. For high-fidelity RETRY of flagged pages,
# rerun at native resolution:
#   lawnlord transcribe --backend local --model qwen2.5vl:7b --max-image-px 0 --force
# --workers=1 because the server runs NUM_PARALLEL=1 (vision serializes anyway).
WORKERS=1

# Stop any transcribe already holding the DB lock (an earlier/abandoned run).
if pgrep -f "lawnlord transcribe" >/dev/null; then
  echo ">> stopping running transcribe..."
  pkill -f "lawnlord transcribe" || true
  sleep 2
fi

for model in "${MODELS[@]}"; do
  echo
  echo "============================================================"
  echo ">> $model   (--workers $WORKERS)"
  echo "============================================================"
  "$LAWNLORD" transcribe --backend local --model "$model" --workers "$WORKERS"
done

echo
echo ">> done. all models swept."
