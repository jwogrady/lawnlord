#!/usr/bin/env bash
# FAST PATH (cosmic) — native 300-DPI transcription via the standalone llama.cpp
# Vulkan vision server. This is the ~10-minute job for the 255-page case
# (~24 pages/min). It REQUIRES the Vulkan server to be up on the Windows host:
#
#     Windows:  scripts/cosmic/serve_vision.cmd 4 2048
#
# Unlike scripts/transcribe_local.sh (the slow ~100-min Ollama path, 1500px on
# CPU), this preflights the server and FAILS LOUDLY if it is not reachable — so a
# down server can never silently downgrade you to the slow path.
#
# Resume is automatic: transcribe skips (page, model) variations already in the DB.
set -euo pipefail

cd "$(dirname "$0")/../.."   # repo root (scripts/cosmic/ -> repo)

if [ -f .env ]; then set -a; . ./.env; set +a; fi

LAWNLORD="${LAWNLORD_BIN:-.venv/bin/lawnlord}"
MODEL="${LLAMACPP_MODEL:-qwen2.5vl:7b}"
WORKERS="${LLAMACPP_WORKERS:-8}"   # 2 x the server's -np 4

# Resolve the vision server. LLAMACPP_HOST wins; else probe the WSL->Windows host
# gateway and localhost on :18082. (serve_vision.cmd binds 127.0.0.1 by default;
# bind --host 0.0.0.0 for WSL to reach it at the host gateway IP.)
GW="$(ip route 2>/dev/null | awk '/default/{print $3; exit}')"
read -r -a CANDS <<< "${LLAMACPP_HOST:-${GW:+http://$GW:18082} http://localhost:18082 http://127.0.0.1:18082}"

vision_up() { curl -fsS -m 4 "$1/health" 2>/dev/null | grep -q '"status"'; }

HOST=""
for cand in "${CANDS[@]}"; do
  if vision_up "$cand"; then HOST="$cand"; echo ">> vision server OK: $cand"; break; fi
  echo ">> not reachable: $cand"
done

if [ -z "$HOST" ]; then
  cat >&2 <<EOF

!! Vulkan vision server is NOT reachable on :18082 — refusing to run.
!! (Falling back to the Ollama path would turn this ~10-min job into ~100 min.)

   Start it on the Windows host, then re-run:
       scripts/cosmic/serve_vision.cmd 4 2048
   Warm it once (the first batch is ~8x slow), then run this script.

   If the server binds 127.0.0.1 (default), WSL cannot reach it — relaunch with
   --host 0.0.0.0 in serve_vision.cmd, or set LLAMACPP_HOST in .env.
EOF
  exit 1
fi

# Stop any transcribe already holding the DB lock (an earlier/abandoned run).
if pgrep -f "lawnlord transcribe" >/dev/null; then
  echo ">> stopping running transcribe..."
  pkill -f "lawnlord transcribe" || true
  sleep 2
fi

echo "============================================================"
echo ">> $MODEL  --backend llamacpp  --workers $WORKERS  host $HOST"
echo ">> native 300 DPI; ~24 pages/min warm (~10 min for 255 pages)"
echo "============================================================"
"$LAWNLORD" transcribe --backend llamacpp --model "$MODEL" \
  --workers "$WORKERS" --llamacpp-host "$HOST"

echo
echo ">> done."
