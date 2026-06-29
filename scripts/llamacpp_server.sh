#!/usr/bin/env bash
# ⚠ NVIDIA / CUDA (cosmos) launcher — UNVERIFIED on real cosmos hardware (2026-06-27).
#   This is the home-box (NVIDIA, native Linux) path: it resolves Ollama's bundled
#   CUDA backend (cuda_v13/cuda_v12). It has NOT been run/benchmarked on cosmos in
#   this reconstruction. The proven cosmic (AMD/Vulkan) path is a DIFFERENT launcher:
#   scripts/cosmic/serve_vision.cmd (+ scripts/cosmic/transcribe_vision.sh).
#   Do not assume CUDA defaults here apply to the AMD box, or vice versa. Validate
#   against scripts/cosmos/capture-cosmos.sh output before trusting this on cosmos.
#
# Standalone llama.cpp vision server with the multimodal projector ON the GPU.
#
# Ollama launches qwen2.5-VL with --no-mmproj-offload, stranding the vision
# encode on the CPU (~64s prefill/page at 300 DPI). Ollama ships its own
# llama.cpp build; running it directly WITHOUT that flag puts the vision tower
# on the GPU and cuts prefill to ~6s (~10x) at full 300 DPI. No new install —
# this reuses the GGUF Ollama already downloaded.
#
# Then point lawnlord at it:
#   lawnlord transcribe --backend llamacpp --model qwen2.5vl:7b
#
# Runs in the foreground (Ctrl-C to stop). Use tmux/nohup to keep it up.
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, regardless of where it's invoked from

# Per-machine config (separated from code): committed defaults are the COSMOS
# profile; a gitignored .env at the repo root overrides any knob. See .env.example.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

MODEL="${MODEL:-qwen2.5vl:7b}"
PORT="${PORT:-18082}"
HOST_ADDR="${HOST_ADDR:-127.0.0.1}"
CTX="${CTX:-8192}"
OLLAMA_LIB="${OLLAMA_LIB:-/usr/local/lib/ollama}"

# Parallel decode slots. Leave unset to let llama-server auto-pick (it chooses 4
# on a 16 GB card). On a smaller card (e.g. the RTX 3080 / 10 GB cosmos box) the
# 4-slot KV cache + GPU mmproj won't fit a 300 DPI page — set NP=2 (or 1) to cap it.
NP="${NP:-}"
PARALLEL_ARGS=()
[ -n "$NP" ] && PARALLEL_ARGS=(-np "$NP")

# The two non-obvious bits (see memory: ollama-vision-cpu-bottleneck):
#  1. GGML_BACKEND_PATH — the CUDA backend lives in a cuda_v* subdir, which the
#     raw binary doesn't auto-discover (Ollama's Go loader normally does).
#  2. --flash-attn + a large batch — without them prefill is ~24s, not ~6s.
CUDA_DIR="$OLLAMA_LIB/cuda_v13"
[ -f "$CUDA_DIR/libggml-cuda.so" ] || CUDA_DIR="$OLLAMA_LIB/cuda_v12"
[ -f "$CUDA_DIR/libggml-cuda.so" ] || { echo "No CUDA backend under $OLLAMA_LIB/cuda_v*" >&2; exit 1; }

# Resolve the GGUF blob path from Ollama's manifest (the mmproj is embedded in
# the same GGUF for qwen2.5-VL, so --mmproj points at it too).
GGUF="$(ollama show --modelfile "$MODEL" 2>/dev/null | awk '/^FROM /{print $2; exit}')"
[ -n "$GGUF" ] && [ -f "$GGUF" ] || { echo "Could not resolve GGUF for $MODEL via 'ollama show'" >&2; exit 1; }

echo ">> model:  $MODEL"
echo ">> gguf:   $GGUF"
echo ">> cuda:   $CUDA_DIR"
echo ">> serving http://$HOST_ADDR:$PORT  (ctx=$CTX, GPU mmproj, flash-attn)"

# Free Ollama's copy of the model from VRAM first (two ~6GB copies won't co-fit).
ollama stop "$MODEL" >/dev/null 2>&1 || true

exec env \
  GGML_BACKEND_PATH="$CUDA_DIR/libggml-cuda.so" \
  LD_LIBRARY_PATH="$CUDA_DIR:$OLLAMA_LIB" \
  "$OLLAMA_LIB/llama-server" \
    -m "$GGUF" --mmproj "$GGUF" \
    -ngl 99 --flash-attn on -b 2048 -ub 2048 \
    "${PARALLEL_ARGS[@]}" \
    -c "$CTX" --port "$PORT" --host "$HOST_ADDR"
