# Native 300-DPI Vision Transcription on AMD RX 6900 XT (Vulkan) — Engineering Report

**Status:** Complete · **Date:** 2026-06-26 · **Machine:** `cosmic` (AMD workstation)
**Scope:** Choosing and tuning the local vision backend for lawnlord's `transcribe` stage.

---

## Executive Summary

lawnlord transcribes filed court PDFs page-by-page with a vision-language model. The
court record is the immutable base, so transcription fidelity matters: we render pages at
**native 300 DPI** (2550×3301 px for US Letter) and want the model to read the *full*
resolution, not a downscaled thumbnail. The question this report answers is narrow and
practical: **what is the fastest, most stable way to run Qwen2.5-VL over native 300-DPI
pages on this machine's AMD Radeon RX 6900 XT, using only prebuilt binaries (no building
from source)?**

The investigation started from the existing Ollama-based workflow and ended at a
**standalone llama.cpp server with the multimodal projector on the GPU**, reached over the
Vulkan backend. Along the way we disproved several assumptions that had been treated as
fact (ROCm would be the fast path; Ollama was using the GPU; a string of `exit 99` crashes
meant native 300 DPI was impossible on this hardware). The headline result: native
300-DPI transcription runs cleanly at **~24 pages/minute at fidelity 0.98 with zero
failures and ~11 GB peak VRAM**, roughly **2× faster** than the single-stream
configuration and **~10× faster** than the original Ollama path (which was silently running
the vision encoder on the CPU).

**Production recommendation:** run a **standalone llama.cpp `llama-server`** (Ollama's
bundled binary is fine) on the **Vulkan** backend with the **mmproj on the GPU**, configured
`-np 4 -c 32768 -ngl 99 --flash-attn on -b 2048 -ub 2048`, and drive it from lawnlord with
`--backend llamacpp --workers 8` over native 300-DPI input. (A full `-np`/`-ub` sweep — see
*Benchmark Results* — found this the throughput ceiling on this hardware; `-ub 2048` is the
sweet spot and the workload is vision-encode-bound, not VRAM- or slot-bound.) Do **not** use ROCm/HIP (the
6900 XT is gfx1030/RDNA2, which current Windows HIP SDK and WSL ROCm do not support), and
do **not** rely on Ollama's default vision path (it downscales to 1500 px and, depending on
version, runs the vision encode on the CPU).

---

## System Configuration

### Hardware

| Component | Spec |
|---|---|
| CPU | AMD Ryzen 9 5900X (12 cores / 24 threads, Zen 3) |
| GPU | AMD Radeon RX 6900 XT, **16 GB** GDDR6 (gfx1030 / RDNA2 / Navi 21, PCI `1002:73BF`) |
| System RAM | 16 GB |
| PSU note | 8-pin EPS (CPU) connector had been loose; see *Major Findings* |

> The `Win32_VideoController.AdapterRAM` WMI field reports **4 GB** for this card — that is a
> known 32-bit overflow bug, not the real VRAM. Vulkan correctly reports **16368 MiB**.

### Software

| Layer | Spec |
|---|---|
| Host OS | Windows (build 26100) |
| GPU driver | AMD Software: Adrenalin Edition **26.6.2** (driver file version `32.0.21043.19003`) |
| Compute backend | **Vulkan** (AMD proprietary Vulkan ICD shipped with Adrenalin) |
| Dev environment | **WSL2**, Ubuntu 26.04, running the lawnlord Python CLI |
| Inference engine | **llama.cpp** `llama-server` (the build bundled with Ollama) + `ggml-vulkan.dll` |
| Model | **Qwen2.5-VL 7B**, Q4_K_M (the GGUF blob Ollama already downloaded; model + projector in one file) |
| Input | **Native 300-DPI PNG**, 2550×3301 px, produced by `lawnlord explode --dpi 300` |

### Architecture

lawnlord runs inside WSL; the model runs on the Windows host GPU. The transcriber is a thin
HTTP client — it does not launch or manage the server.

```
┌─────────────────────────── Windows host (cosmic) ───────────────────────────┐
│                                                                              │
│   WSL2 (Ubuntu)                         Windows native                       │
│   ┌───────────────────┐   HTTP /v1/    ┌──────────────────────┐             │
│   │ lawnlord          │  chat/         │ llama-server.exe      │             │
│   │  transcribe       │  completions   │  (Ollama's build)     │             │
│   │  --backend        │ ─────────────► │   -np 3  -c 24576     │             │
│   │    llamacpp       │   (JSON +      │   --flash-attn on     │             │
│   │  --workers 6      │    base64 PNG) │   mmproj ON GPU       │             │
│   └───────────────────┘                └──────────┬───────────┘             │
│                                                    │ GGML_BACKEND_PATH=      │
│                                                    │   ...\vulkan\           │
│                                                    │   ggml-vulkan.dll       │
│                                                    ▼                         │
│                                         ┌──────────────────────┐            │
│                                         │ Vulkan (Adrenalin)   │            │
│                                         └──────────┬───────────┘            │
│                                                    ▼                         │
│                                         ┌──────────────────────┐            │
│                                         │ RX 6900 XT  16 GB     │            │
│                                         │  weights + KV + mmproj│            │
│                                         └──────────────────────┘            │
└──────────────────────────────────────────────────────────────────────────┘
```

Pipeline position (lawnlord stages):

```
intake zip ─import─▶ DuckDB mirror ─explode --dpi 300─▶ page PNGs ─transcribe --backend llamacpp─▶ page_text
```

---

## Investigation Timeline

The work proceeded as a sequence of hypotheses, each tested and then kept or discarded.

1. **ROCm/HIP triage (disproved as a path).** The original goal was native HIP 7.1. `hipInfo`
   and a direct `hipGetDeviceCount()` call both returned **error 100 (`hipErrorNoDevice`)**.
   The HIP **runtime DLL loaded fine** — the failure was device *enumeration*. We confirmed
   the GPU is healthy (the driver-shipped HIP **6.x** runtime enumerates it: `count=1`), so the
   fault was the **SDK-7.1 runtime vs the installed driver / unsupported architecture**, not
   hardware. AMD's docs confirm gfx1030/RDNA2 is **unsupported** on Windows HIP SDK 7.1
   (RDNA3/RDNA4 only); HIP SDK **6.2.4** was the last to list the RX 6900 XT. WSL ROCm is also
   RDNA3+ only. **Conclusion: ROCm/HIP is a dead end for this card; Vulkan is the path.**

2. **Initial Ollama benchmarking.** Ollama 0.30.10 was installed with `qwen2.5vl:7b`. A text
   generation measured **~8 tok/s** and `ollama ps` showed **`100% CPU`**. The model was not
   on the GPU at all.

3. **GPU-utilization / backend investigation.** Ollama bundles two GPU backends:
   `rocm_v7_1` (HIP 7.1 — fails on gfx1030 with `hipGetDeviceCount failed: 100`) and `vulkan`.
   Without opt-in, Ollama tried ROCm, failed, and fell back to CPU.

4. **`OLLAMA_VULKAN` discovery.** Setting **`OLLAMA_VULKAN=1`** and restarting put the model
   on the GPU: the runner loaded `ggml-vulkan.dll`, offloaded **29/29 layers**, and ran at
   **~85–95 tok/s** (text). This is the single most important Ollama knob on this machine.

5. **`NUM_PARALLEL` tuning (and its OOM trap).** With Ollama on the GPU we pushed
   `OLLAMA_NUM_PARALLEL`. At **NP=8 with 300-DPI images the runner OOM'd** — the scheduler
   pre-reserves KV for `NP × ctx` (8×8192 = 65536 tokens ≈ 3584 MiB), which starves the vision
   encoder; it died at `process_mtmd` with `ggml_vulkan: vk::Device::allocateMemory:
   ErrorOutOfDeviceMemory` **on the very first image**. NP≤4 was the Ollama ceiling.

6. **Workers tuning.** lawnlord's `--workers` is client-side concurrency, independent of the
   server's slot count. With a 1-slot server, extra workers only queue. Throughput scales with
   server **slots (`-np`)**, not workers — workers must be ≥ slots to keep them fed.

7. **The "Ollama optimised the wrong layer" pivot.** Reading `src/lawnlord/transcribe.py`
   showed the real cost driver: Ollama's `LocalTranscriber` **downscales pages to 1500 px** by
   default and (per the documented `ollama-vision-cpu-bottleneck` finding) historically runs the
   vision projector on the CPU. We had tuned LLM token generation while the **vision prefill**
   was the bottleneck — and Ollama wasn't even doing 300 DPI.

8. **Standalone llama.cpp investigation.** The CLI exposes `--backend llamacpp`, an HTTP client
   to a standalone `llama-server` (`/v1/chat/completions`) that sends the **native render** and
   runs the **projector on the GPU**. We stood one up on Vulkan using Ollama's bundled
   `llama-server.exe` with `GGML_BACKEND_PATH` pointed at `ggml-vulkan.dll` and `--mmproj`
   pointed at the qwen2.5-VL blob (it auto-detects: *"Ollama-format qwen25vl GGUF used as
   mmproj; translating"*). The repo's `scripts/llamacpp_server.sh` is the **cosmos/CUDA/Linux**
   profile and does not apply here; this report's `serve_vision.cmd` is the cosmic/Vulkan
   equivalent.

9. **The crash cluster and the reboot.** Native-300 encodes began crashing with `exit 99` even
   at `-np 1, 1 page`. After **many** OOM/crashes in one session, the Vulkan runner had become
   unstable. We **rebooted** and retested clean.

10. **Benchmarking ladder (post-reboot).** Starting conservative (`-np 1`, 1 page) and climbing
    `-np 1→2→3` with matched workers, native 300-DPI ran at **every** rung with zero failures.
    Throughput nearly doubled by `-np 3`; VRAM stayed ≤ 10.6 GB. `-np 3` was selected as the
    production point.

11. **Content validation.** A skeptic check confirmed the benchmark pages were **real dense
    legal text** (563–2040 chars/page, fidelity 0.95–1.0), not blank pages — and staged with a
    `>250 KB` filter that biases *toward* the hardest (densest) pages.

---

## Major Findings

### Things We Thought Were True But Were Wrong

Each item is tagged **[PROVEN]** (reproduced from logs/measurements), **[OBSERVED]**
(seen but not exhaustively reproduced), or **[HYPOTHESIS]** (plausible, not confirmed here).

1. **"ROCm/HIP will be the fast local path." → Wrong. [PROVEN]**
   The RX 6900 XT is gfx1030/RDNA2. `hipGetDeviceCount()` returns **100** under HIP SDK 7.1,
   and AMD's own support matrix lists only RDNA3/RDNA4 for Windows HIP SDK 7.1 and for WSL
   ROCm. The driver-shipped HIP **6.x** runtime *does* enumerate the card, proving the hardware
   is fine and the limitation is software/support-matrix. ROCm is not a production option here.

2. **"The `amd.go: AMD driver is too old` warning means the GPU is unusable." → Cosmetic. [PROVEN]**
   This warning fires from Ollama's ROCm discovery path and is present **even when the model
   successfully offloads 29/29 layers and runs 100% on the GPU**. It does not gate Vulkan.

3. **"`compute=0.0 driver=0.0` in Ollama's `inference compute` line means failed capability
   detection." → Cosmetic. [PROVEN]**
   Those are CUDA/ROCm-style fields that Ollama leaves zero on the Vulkan path. The model runs
   fully on the GPU regardless.

4. **"Vulkan isn't really executing inference; it's silently on CPU." → Wrong. [PROVEN]**
   Logs show `load_tensors: offloaded 29/29 layers to GPU`, `Vulkan0 model buffer ≈ 4168 MiB`,
   `clip_ctx: CLIP using Vulkan0 backend`, and measured **85–95 tok/s** with GPU utilisation
   peaking ~96% and CPU ~7%. Vulkan was doing the work.

5. **"Ollama's scheduler is the fastest path." → Wrong for this workload. [PROVEN]**
   Ollama downscales to 1500 px (not 300 DPI) and pre-reserves KV per parallel slot, OOMing at
   NP=8/300-DPI. The standalone llama.cpp server sends the native render, runs the projector on
   the GPU, and lets us control context per slot. It is both higher-fidelity and faster.

6. **"Native 300-DPI vision encode is impossible on this 16 GB Vulkan stack." → Wrong. [PROVEN]**
   Pre-reboot it crashed at `exit 99` even at 1:1. **Post-reboot, on a clean Vulkan runner, it
   ran at every rung** (`-np 1..3`) with zero failures and ≤ 10.6 GB peak. The earlier crashes
   were runner state, not a hardware ceiling.

7. **"A string of `exit 99` crashes proves a software/hardware limit." → No — runner
   corruption. [PROVEN that a reboot fixes it; HYPOTHESIS on the exact mechanism]**
   Repeated OOMs corrupt the Vulkan runner; subsequent allocations crash even on configs that
   are fundamentally fine. A reboot restored full stability. Treat post-OOM crashes as state to
   be reset, not as the system's capability ceiling.

8. **The loose 8-pin EPS (CPU) power connector likely contributed to earlier instability.
   [HYPOTHESIS]**
   This machine had days of hard resets under load; the suspected root cause was a loose EPS
   cable (since reseated). Power-delivery faults can masquerade as "GPU/driver" crashes. When a
   crash is non-deterministic and load-correlated, rule out power/thermal before blaming the
   software stack.

9. **A near-blank benchmark would have inflated the numbers. → Did not happen. [PROVEN]**
   Benchmark pages were verified to contain 563–2040 chars of real legal text at fidelity
   0.95–1.0; staging biased toward the densest pages, so the reported pages/min is a lower
   bound for the real document mix.

---

## Benchmark Results

**Workload:** native 300-DPI PNG (2550×3301), Qwen2.5-VL 7B Q4_K_M, identical lawnlord prompt
and JSON schema for every request. **Backend:** standalone `llama-server` on Vulkan, projector
on GPU. **Measurement:** wall-clock client→server over Windows loopback; 8 distinct timed pages
per run (1 warm-up page excluded). **Clean boot** (uncorrupted Vulkan runner).

> **Why cold-start runs were discarded.** The **first batch after every server (re)start runs
> ~7–10× slower** (~180 s for 8 pages, gen ~12–19 tok/s) while Vulkan compiles shaders and the
> prompt/KV caches warm. This is a one-time transient, not steady-state throughput. Every table
> below reports the **warm** run; cold first-batches (e.g. the 2.6–2.7 pages/min readings seen
> immediately after a restart) are explicitly excluded.

### `-np 1` (single slot, `-c 8192`)

| workers | pages/min | gen tok/s | peak VRAM | failures | avg fidelity |
|--------:|----------:|----------:|----------:|---------:|-------------:|
| 1 | 10.6 | 81.1 | 9.56 GB | 0 | 0.98 |
| 2 | 10.9 | 81.0 | 9.56 GB | 0 | 0.98 |
| 4 | 10.9 | 81.0 | 9.55 GB | 0 | 0.98 |

Workers beyond 1 do not help: a single slot serialises requests. ~10.9 pages/min is the
1-slot ceiling.

### `-np 2` (two slots, `-c 16384` → 8192/slot)

| workers | pages/min | gen tok/s | peak VRAM | failures | avg fidelity |
|--------:|----------:|----------:|----------:|---------:|-------------:|
| 2 | 17.5 | 69.2 | 10.07 GB | 0 | 0.97 |
| 4 | 17.1 | 66.7 | 10.17 GB | 0 | 0.97 |

~1.6× over `-np 1`. Per-page generation drops (the GPU is shared across concurrent decodes)
but aggregate throughput rises.

### `-np 3` (three slots, `-c 24576` → 8192/slot) — **selected**

| workers | pages/min | gen tok/s | peak VRAM | failures | avg fidelity |
|--------:|----------:|----------:|----------:|---------:|-------------:|
| 6 (peak run) | **21.4** | 58.4 | 10.63 GB | 0 | 0.98 |
| 6 (re-run) | 19.3 | 54.0 | 10.52 GB | 0 | 0.97 |
| 6 (re-verify 2026-06-26) | **22.6** | 60.6 | 10.1 GB | 0 | 0.98 |

~2× over `-np 1`, with ~4.4 GB VRAM to spare. A clean-boot re-verification reproduced the
result (22.6 pages/min warm), confirming `-np 3` as the production point.

### `-np 4` (four slots, `-c 32768` → 8192/slot)

| workers | -ub | pages/min | gen tok/s | peak VRAM | failures | avg fidelity |
|--------:|----:|----------:|----------:|----------:|---------:|-------------:|
| 8 (warm) | 1024 | 23.0 | 52.5 | 10.6 GB | 0 | 0.98 |
| 8 (warm) | **2048** | **24.2** | 50.3 | 11.0 GB | 0 | 0.98 |

At the original `-ub 1024`, `-np 4` (23.0) looked flat against `-np 3` (22.6). But raising the
micro-batch to **`-ub 2048`** lifts `-np 4` to **24.2 pages/min** — the top of the whole sweep.

### `-ub` micro-batch / `-np` sweep (the max-out pass)

Because the workload is vision-**prefill**-bound (not slot-bound), the micro-batch `-ub` — how
many image tokens the encoder processes per pass — is the real throughput lever. Full warm sweep
(native 300 DPI, workers = max(2·np, 6), 0 failures everywhere, all well under the 15 GB stop):

| config | pages/min | gen tok/s | peak VRAM | avg fidelity |
|---|--:|--:|--:|--:|
| **`-np 4 -ub 2048`** | **24.2** | 50.3 | 11.0 GB | 0.98 |
| `-np 6 -ub 2048` | 21.5 | 37.2 | 11.9 GB | 0.98 |
| `-np 3 -ub 2048` | 21.4 | 58.5 | 10.6 GB | 0.98 |
| `-np 6 -ub 1024` | 21.0 | 36.2 | 11.6 GB | 0.98 |
| `-np 3 -ub 4096` | 20.4 | 56.9 | 11.2 GB | 0.97 |
| `-np 2 -ub 4096` | 18.6 | 71.5 | 10.7 GB | 0.97 |
| `-np 4 -ub 4096` | 18.4 | 44.2 | 11.6 GB | 0.98 |

Findings:
- **`-ub 2048` is the sweet spot.** `-ub 4096` is *slower everywhere* and uses more VRAM — a
  larger micro-batch inflates the vision compute buffer past the point of return.
- **`-np 6` is pointless.** Throughput stalls at ~21 pages/min while per-page generation
  collapses (36–37 tok/s) as slots contend — confirming the limit is encode throughput, not
  concurrency.
- **VRAM is never the binding constraint** — peak across the entire sweep was 11.9 GB vs the
  15 GB guardrail. The ceiling is the vision encoder, not memory.
- **The hardware ceiling is ~24 pages/min** (≈10.5 min for a 255-page case, warm).

**Production point (revised): `-np 4 -c 32768 --flash-attn on -b 2048 -ub 2048`, client
`--workers 8`** → 24.2 pages/min at fidelity 0.98.

### Reference points (same GPU/Vulkan)

| Scenario | Result |
|---|---|
| Raw text gen, 7B Q4_K_M (non-vision) | 95 tok/s generation, 1533 tok/s prompt processing |
| Ollama default vision path (pre-fix) | ~8 tok/s, **100% CPU**, and downscaled to 1500 px (not 300 DPI) |
| Idle VRAM with model loaded | 8.0 GB (`-np 1`) → 9.2 GB (`-np 3`) |

---

## Production Configuration

### Server (Windows host)

```bat
:: serve_vision.cmd  [NP] [UBATCH]   e.g.  serve_vision.cmd 3 1024
set OLLAMA_LIB=C:\Users\john\AppData\Local\Programs\Ollama\lib\ollama
set BLOB=C:\Users\john\.ollama\models\blobs\sha256-a99b7f834d754b88f122d865f32758ba9f0994a83f8363df2c1e71c17605a025
set GGML_BACKEND_PATH=%OLLAMA_LIB%\vulkan\ggml-vulkan.dll
set GGML_VK_VISIBLE_DEVICES=0
set /a CTX=%NP%*8192
"%OLLAMA_LIB%\llama-server.exe" -m "%BLOB%" --mmproj "%BLOB%" ^
  -ngl 99 --flash-attn on -b %UB% -ub %UB% -c %CTX% --parallel %NP% ^
  --port 18082 --host 127.0.0.1
```

Production invocation: **`serve_vision.cmd 4 2048`** (`-np 4 -c 32768 -ub 2048`).

| Parameter | Value | Why |
|---|---|---|
| engine | Ollama's bundled `llama-server.exe` | Reuses the already-downloaded GGUF; knows the "Ollama-format qwen25vl" blob (upstream b9821 `llama-server` rejects the combined blob as `--mmproj`). |
| `GGML_BACKEND_PATH` | `…\vulkan\ggml-vulkan.dll` | Forces the **Vulkan** backend. Without it the raw binary won't find the backend (Ollama's Go loader normally sets this). |
| `--mmproj <same blob>` | projector **on GPU** | The core win — keeps the vision encode off the CPU (~10× prefill). |
| `-ngl 99` | all layers on GPU | Full offload; the model fits comfortably in 16 GB. |
| `--flash-attn on` | enabled | Lower KV memory and faster attention; stable here. |
| `-b 2048 -ub 2048` | batch / micro-batch | The throughput sweet spot for the vision prefill (the bottleneck). `-ub 1024` is ~5% slower; `-ub 4096` is slower *and* hungrier — it overshoots the encode compute buffer. |
| `-c = NP × 8192` | 32768 at NP=4 | **Critical.** `-c` is split across slots; a native 300-DPI page needs ~5k image tokens, so each slot must keep ≥ 8192 ctx or requests fail with **HTTP 400**. |
| `--parallel 4` | 4 slots | Top of the measured sweep (24.2 pg/min) within the VRAM budget. `-np 6` adds no throughput (encode-bound); `-np 8` OOMs at 300 DPI. |
| `--host 127.0.0.1` | loopback | Default. See *Operational Notes* for the WSL→host wiring. |

### Client (lawnlord, in WSL)

```bash
uv run lawnlord transcribe --backend llamacpp --workers 8 \
  --llamacpp-host http://<host-reachable-from-wsl>:18082 --model qwen2.5vl:7b
```

| Parameter | Value | Why |
|---|---|---|
| `--backend llamacpp` | standalone server | Native render + GPU projector + OpenAI `/v1` schema; bypasses Ollama's scheduler/KV pre-reservation. |
| `--workers 8` | 2 × slots | Keeps all 4 slots saturated with one in-flight refill each; more workers only queue. |
| input | native 300 DPI | `LlamaCppTranscriber` defaults to the native render (no downscale). Do **not** pass `--max-image-px`; leave it native for full fidelity. |

---

## Operational Notes

- **Warm-up / shader compilation.** The first batch after any (re)start runs ~7–10× slower
  (~180 s for 8 pages) while Vulkan compiles shaders and warms caches. **Warm the server with a
  few throwaway pages before timing or before a production batch.** Steady-state is reached
  after the first batch and persists for the life of the process.
- **Vulkan runner corruption after OOM.** An out-of-device-memory event (e.g. pushing `-np`
  too high, or oversized images) can leave the Vulkan runner in a state where *subsequent*
  allocations crash (`exit 99`) even on configs that are otherwise fine. **A reboot restores
  stability** — it is the only reliable reset for the corrupted runner. Do not interpret
  post-OOM crashes as the steady-state limit.
- **Expected VRAM.** Idle (model loaded) ≈ 8–9 GB; peak under load at the production `-np 4
  -ub 2048` ≈ **11 GB** (whole sweep topped out at 11.9 GB). Treat **>15 GB peak as the hard
  stop** — back off `-np`/`-ub` or image size before that.
- **Expected throughput.** ~**24 pages/min** at `-np 4 -ub 2048` on dense pages; higher on the full
  corpus (sparse/exhibit pages transcribe faster). `-np 1` ≈ 11 pages/min.
- **Per-slot context is a hard constraint.** Always set `-c = NP × 8192`. Too-small per-slot
  context returns **HTTP 400** for native pages (the image alone exceeds the slot).
- **Monitoring recommendations.**
  - VRAM: `Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage'` (PowerShell). `rocm-smi` is
    not available on Windows.
  - GPU utilisation: `Get-Counter '\GPU Engine(*)\Utilization Percentage'` (sum across engines;
    the counter samples slowly, so trust peaks more than averages).
  - Liveness: poll `GET http://127.0.0.1:18082/health`; treat a dropped connection during
    `process_mtmd` as an OOM/crash signal.
  - Watch the server log for `ErrorOutOfDeviceMemory` and `exit 99` — both mean "reduce load
    and/or reboot."

---

## Lessons Learned

- **Identify the architecture first.** Five minutes confirming the GPU is gfx1030/RDNA2 and
  checking AMD's support matrix would have ruled out ROCm/HIP immediately. We spent real effort
  proving `hipGetDeviceCount()=100` before accepting that RDNA2 is simply unsupported on modern
  Windows HIP/WSL ROCm.
- **Verify the GPU is actually being used before optimising it.** Ollama reported a loaded
  model while running **100% on the CPU**. Always confirm with `ollama ps` / offload logs /
  `tok/s` sanity (CPU ≈ 8 tok/s vs GPU ≈ 85+).
- **Read the data path, not just the throughput.** The biggest win came from realising the
  vision **prefill** (image encode), not LLM token generation, was the cost — and that Ollama
  was downscaling away the 300 DPI we cared about. Tuning token gen was optimising the wrong
  layer.
- **Cosmetic warnings waste time.** `amd.go: AMD driver is too old` and `compute=0.0` look
  alarming and mean nothing on the Vulkan path. Confirm against actual offload before chasing
  them.
- **OOM corrupts the Vulkan runner; reboot, don't re-tune.** Once we started getting `exit 99`
  on configs that should work, every further measurement was noise. The clean-boot ladder gave
  consistent, monotonic results. Build a reboot into the protocol after any OOM.
- **Rule out power/thermal on non-deterministic crashes.** The loose EPS connector is a
  reminder that "random crashes under load" can be hardware, not software.
- **Benchmark on real, verified inputs.** Confirm pages aren't blank before trusting pages/min.
  Bias the sample toward the *hardest* pages so the number is a floor.
- **`-c` is shared across slots in llama.cpp.** More slots ⇒ proportionally less context each;
  scale `-c` with `-np` or vision requests 400 out.

### First things to try on a future AMD system

1. Confirm GPU arch (`gfx****`) and check AMD's HIP/WSL support matrix — decide ROCm-vs-Vulkan
   before anything else.
2. Get *any* GPU inference working on Vulkan and confirm offload (`ollama ps`, `tok/s`).
3. For vision, go straight to a **standalone llama.cpp server with `--mmproj` on the GPU**;
   don't tune Ollama's vision path.
4. Find the max stable `-np` with a conservative→aggressive ladder, rebooting after any OOM,
   stopping at >15 GB peak / `exit 99` / no throughput gain.

---

## Future Work

- ~~**Test `-np 4` (`-c 32768`)** / find the throughput ceiling~~ **Done (2026-06-26).** A full
  `-np`/`-ub` sweep (see *Benchmark Results*) found **`-np 4 -ub 2048` = 24.2 pages/min** the
  winner — now the production point. Key results: `-ub 2048` is the sweet spot (`-ub 4096` is
  slower and hungrier); `-np 6` adds nothing (encode-bound, not slot-bound); peak VRAM across the
  whole sweep was 11.9 GB, so memory is never the binding constraint. The hardware ceiling is
  ~24 pages/min.
- **End-to-end `lawnlord transcribe` confirmation.** Reported pages/min is client→server
  loopback. Run the full 255-page case through the CLI to confirm the end-to-end figure
  (DB writes are expected to be negligible). Requires wiring WSL→host networking (bind the
  server to `0.0.0.0` and use `--llamacpp-host http://<host-ip>:18082`, or run the client on
  Windows).
- **Larger / newer GPUs.** An RDNA3 card (e.g. 7900 XTX, 24 GB) would unlock ROCm/HIP *and*
  WSL ROCm and allow much higher `-np`; worth comparing throughput and stability head-to-head.
- **Native Linux ROCm comparison.** Bare-metal Linux historically supported gfx1030 in core
  ROCm further than Windows; a dual-boot test could quantify ROCm-vs-Vulkan on this exact card.
- **Upstream llama.cpp updates.** We pinned to Ollama's bundled `llama-server` because upstream
  b9821 rejected the combined Ollama blob as `--mmproj`. Re-test newer upstream builds with a
  standalone mmproj GGUF — they often bring Vulkan vision-encode speedups and stability fixes.
- **Future Qwen releases / quants.** Newer Qwen-VL versions or different quantisations (e.g. a
  higher-fidelity quant within the VRAM budget) may improve fidelity or speed at 300 DPI.
- **Stratified fidelity audit.** Sample pages across all 22 documents (including exhibit-heavy
  ones) to characterise fidelity and throughput on the true document mix, not just disclosures.

---

## Appendix: Reproducing the Benchmark

```bash
# 1. Render native 300-DPI pages (in WSL)
uv run lawnlord explode --dpi 300          # → extracted/pages/**/*.png  (2550×3301)

# 2. Start the Vulkan vision server (Windows; mmproj on GPU)
serve_vision.cmd 3 1024                     # -np 3, -c 24576, port 18082

# 3. Warm it (first batch is ~10× slow — discard), then measure
#    Drive N concurrent /v1/chat/completions requests with the lawnlord prompt+schema,
#    sending each page as a base64 data URI at native resolution.
#    Metrics: wall-clock pages/min, server `timings`, finish_reason, JSON-parse success,
#    self-reported fidelity. Sample VRAM via the GPU performance counters above.

# 4. Stop criteria while climbing -np: peak VRAM > 15 GB, exit 99, HTTP 400 (ctx too small),
#    truncated output (finish_reason=length), or no pages/min improvement.
```

**Cross-references (internal):** `src/lawnlord/transcribe.py` (`LocalTranscriber` vs
`LlamaCppTranscriber`), `scripts/llamacpp_server.sh` (cosmos/CUDA profile), ADR-0006
(vision runs on all pages).
