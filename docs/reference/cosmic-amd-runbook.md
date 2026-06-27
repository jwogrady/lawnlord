# cosmic runbook — AMD/Vulkan native-300-DPI transcription (the proven fast path)

Reproduce, from scratch, the best **evidence-based** `cosmic` transcription path: the standalone
**llama.cpp Vulkan vision server** driven via `--backend llamacpp`. This is the ~10-minute job for
the 255-page case. Every number below is from the captured 2026-06-26 sweep
(`scripts/cosmic/sweep_results.txt`, `scripts/cosmic/bench_np4_warm.out`) — not from memory.

> **Machine:** `cosmic` — AMD Radeon RX 6900 XT (RDNA2/gfx1030, 16 GB), Windows 11 + WSL2 (Ubuntu).
> ROCm/HIP is unsupported on gfx1030, so inference runs on the **Windows host** via **Vulkan**;
> lawnlord runs in WSL and reaches the server over HTTP. Full spec: `development-machine.md`.

---

## What runs where

```
WSL2 (Ubuntu)                         Windows host
─────────────                         ────────────
lawnlord transcribe                   llama-server.exe (Ollama's bundled build)
  --backend llamacpp     ── HTTP ──▶    Vulkan ggml backend, qwen2.5-VL projector ON GPU
  (scripts/cosmic/                       (scripts/cosmic/serve_vision.cmd)
   transcribe_vision.sh)               port 18082
```

The server is **NVIDIA-free**: it uses `ggml-vulkan.dll` from Ollama's lib dir. The GGUF + mmproj
are the qwen2.5-VL blob Ollama already downloaded — no extra model install.

---

## 1. Required runtime (lives OUTSIDE git — Layer 5)

| Component | Where | Notes |
|---|---|---|
| Ollama for Windows | default install (`C:\Users\<you>\AppData\Local\Programs\Ollama`) | provides `lib\ollama\llama-server.exe` + `lib\ollama\vulkan\ggml-vulkan.dll` |
| qwen2.5-VL blob | `C:\Users\<you>\.ollama\models\blobs\sha256-…` | `ollama pull qwen2.5vl:7b` |
| AMD Vulkan driver | Windows (Adrenalin) | gfx1030 / RDNA2 |
| lawnlord + uv | WSL2 | `uv sync` in the repo |

> Paths and the blob **sha256 are machine-specific** and change on a model re-pull. `serve_vision.cmd`
> currently hardcodes them — see Troubleshooting if yours differ.

## 2. Setup (once)

```powershell
# Windows (PowerShell): install Ollama, pull the model, confirm the blob exists
ollama pull qwen2.5vl:7b
ollama list                      # qwen2.5vl:7b present
# Find the blob path the server needs:
type "$env:USERPROFILE\.ollama\models\manifests\registry.ollama.ai\library\qwen2.5vl\7b"
```
```bash
# WSL: seed the machine profile into a gitignored .env (profiles are SELECTED, not edited)
cd ~/workspace/lawnlord
cp profiles/cosmic-amd.env .env
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env   # optional; only for cloud escalation. NEVER commit .env
uv sync
```

`profiles/cosmic-amd.env` sets `OLLAMA_HOST=http://172.31.128.1:11434` (host gateway),
`LLAMACPP_HOST=http://172.31.128.1:18082`, `LLAMACPP_NP=4`, `LLAMACPP_BACKEND=vulkan`. Shared knobs
(model, port, ctx, flash, batch/ubatch) are documented in `profiles/common.env`.

## 3. Launch the Vulkan vision server (Windows host)

```bat
:: Windows cmd, from C:\ai (or wherever the vaulted scripts live)
serve_vision.cmd 4 2048
```
This launches `llama-server.exe -ngl 99 --flash-attn on -b 2048 -ub 2048 -c 32768 --parallel 4`
on `http://127.0.0.1:18082` — the benchmarked production point (`-np 4 -ub 2048`).

> **WSL reachability:** `serve_vision.cmd` binds `127.0.0.1` by default. WSL reaches the Windows host
> at the **gateway IP** (`172.31.128.1`), so to drive it from WSL you must either relaunch the server
> with `--host 0.0.0.0`, or set `LLAMACPP_HOST` in `.env`. See Troubleshooting.

**Warm it once** — the first batch is ~8× slow (cold prefill). Run a throwaway page, then proceed.

## 4. Health check (WSL)

```bash
curl -fsS http://172.31.128.1:18082/health    # expect {"status":"ok"}
```
`scripts/cosmic/transcribe_vision.sh` does this automatically and **refuses to run** if the server is
down (so it never silently drops to the ~100-min Ollama path).

## 5. Transcribe (WSL)

```bash
# Preferred — preflights health, then runs the fast path:
scripts/cosmic/transcribe_vision.sh

# Equivalent explicit form:
uv run lawnlord transcribe --backend llamacpp --model qwen2.5vl:7b \
  --workers 8 --llamacpp-host http://172.31.128.1:18082
```
`--workers 8` = 2× the server's `-np 4`. Resume is automatic: already-transcribed `(page, model)`
variations are skipped.

## 6. Benchmark (WSL)

```bash
# bench.py {llamacpp|ollama} <host> <maxpx:0=native> <pagedir> <workers>
uv run python scripts/cosmic/bench.py llamacpp http://172.31.128.1:18082 0 <pagedir> 8
# Full -np/-ub sweep (Windows): scripts/cosmic/sweep.ps1  → sweep_results.txt
```

## 7. Expected performance (proven — 2026-06-26 sweep)

| config | pages/min | gen tok/s | peak VRAM | fidelity |
|---|---|---|---|---|
| **`-np 4 -ub 2048` (production)** | **24.2** | 50.3 | ~11.0 GB | 0.98 |
| `-np 6 -ub 2048` | 21.5 | 37.2 | ~11.9 GB | 0.98 |
| `-np 3 -ub 2048` | 21.4 | 58.5 | ~10.6 GB | 0.98 |
| `-np 4 -ub 4096` | 18.4 | 44.2 | ~11.6 GB | 0.98 |

All native 300 DPI, qwen2.5vl:7b, 0 failures. Warm 8-page micro-bench at `-np 4`: 23.0 pg/min
(`bench_np4_warm.out`). **`-np 4 -ub 2048` is the winner** — `ub > 2048` and `np > 4` both regress.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `transcribe_vision.sh` refuses: server not reachable | bound `127.0.0.1`; WSL hits the gateway IP | relaunch with `--host 0.0.0.0` in `serve_vision.cmd`, or set `LLAMACPP_HOST` in `.env` |
| ~8 tok/s, CPU-bound | Vulkan backend not engaged | ensure `OLLAMA_VULKAN=1` on the Windows host; confirm `ggml-vulkan.dll` path |
| First batch ~8× slow | cold prefill | warm the server once before timing/production |
| Server won't start / "no such blob" | model re-pulled → new sha256 | re-resolve the blob path; update the `BLOB=` line in `serve_vision.cmd` |
| OOM / runner crash (exit 0xe06d7363) | too many slots (≥8 OOM'd ~15.4 GB) | stay at `-np 4`; reboot to clear a corrupted Vulkan runner |
| Falls back to ~100 min | Ollama `--backend local` path (1500px, CPU mmproj) | that is the SLOW path (`scripts/transcribe_local.sh`); use the llamacpp path above |

---

*See also:* [`development-machine.md`](development-machine.md) ·
[`../performance/native-300dpi-vulkan-benchmark.md`](../performance/native-300dpi-vulkan-benchmark.md) ·
[`../performance/cosmic-backend-comparison.md`](../performance/cosmic-backend-comparison.md) ·
[`multi-machine-setup.md`](multi-machine-setup.md) · [`../../scripts/cosmic/README.md`](../../scripts/cosmic/README.md)
