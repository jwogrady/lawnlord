# Development Machine Reference — `cosmic`

**Authoritative specification of the reference workstation for high-performance local
multimodal inference and lawnlord development.**

Inspected live on 2026-06-26. Where a value can drift (driver versions, env vars), the
command used to read it is shown so it can be re-verified. This document is the source of
truth for rebuilding or cloning this environment.

---

## Executive Summary

`cosmic` is the reference workstation for **local, full-fidelity multimodal inference** —
specifically running **Qwen2.5-VL** over **native 300-DPI** legal-document page images — and
for developing the **lawnlord** case-understanding engine.

It is an AMD workstation: a Ryzen 9 5900X with a Radeon RX 6900 XT (16 GB). Because the GPU
is RDNA2 (gfx1030), **production inference runs on the Vulkan backend**, not ROCm/HIP (which
does not support this card on Windows/WSL — see *AMD Graphics Stack*). lawnlord runs inside
**WSL2**; the model runs on the **Windows host** via a standalone **llama.cpp `llama-server`**
that lawnlord talks to over HTTP. The validated production result is **~24 pages/min at
fidelity 0.98**, ~11 GB peak VRAM, zero failures (the `-np 4 -ub 2048` sweep winner). See
[`docs/performance/native-300dpi-vulkan-benchmark.md`](../performance/native-300dpi-vulkan-benchmark.md)
for the benchmark study and [`docs/performance/cosmic-backend-comparison.md`](../performance/cosmic-backend-comparison.md)
for why this backend (llama.cpp/Vulkan) beats the Ollama path.

---

## Hardware

| Component | Value |
|---|---|
| **CPU** | AMD Ryzen 9 5900X — 12 cores / 24 threads (Zen 3), base 3.70 GHz (`MaxClockSpeed=3701`), 64 MB L3 |
| **RAM (installed)** | 16 GB (2 × 8 GB), G.Skill Trident Z RGB `F4-3200C16-8GTZR` |
| **RAM (speed)** | **Running at 2133 MT/s** though rated DDR4-3200 — XMP/DOCP is **not** enabled (see note) |
| **GPU** | AMD Radeon RX 6900 XT, **16 GB** GDDR6 (Vulkan reports `16368 MiB`) |
| **GPU arch** | RDNA2 / **gfx1030** / Navi 21 |
| **GPU PCI** | `PCI\VEN_1002&DEV_73BF&SUBSYS_69011EAE&REV_C0` (device `1002:73BF`) |
| **Storage** | Samsung SSD **980 PRO 1 TB** (NVMe); C: ≈ 268 GB free / 181 GB used |
| **Motherboard** | MSI **MPG X570S CARBON MAX WIFI** (MS-7D52), rev 1.0 |
| **BIOS** | American Megatrends **1.D1**, released 2025-09-21 |

> **Note — RAM speed.** The kit is rated DDR4-3200 (C16) but is running at **2133 MT/s** because
> XMP/DOCP is off. Inference here is GPU-bound (CPU near-idle), so this does not affect the
> production throughput, but enabling DOCP in BIOS is recommended for general dev work.
>
> **Note — power delivery.** This board's **8-pin EPS (CPU) connector** was previously loose and
> caused load-correlated hard resets; it has been reseated. If non-deterministic crashes recur,
> check power/thermal before the software stack.

> The WMI `AdapterRAM` field reports the GPU as **4 GB** — a known 32-bit overflow, **not** the
> real VRAM. Trust Vulkan's `16368 MiB`.

**Re-verify:**
```powershell
Get-CimInstance Win32_Processor | fl Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed
Get-CimInstance Win32_PhysicalMemory | ft Capacity,Speed,ConfiguredClockSpeed,PartNumber
Get-CimInstance Win32_VideoController | ? Name -match Radeon | fl Name,DriverVersion,PNPDeviceID
Get-CimInstance Win32_BaseBoard | fl Manufacturer,Product,Version
Get-CimInstance Win32_BIOS | fl SMBIOSBIOSVersion,ReleaseDate
```

---

## Operating System

| Item | Value | Source |
|---|---|---|
| Windows edition | Windows 11 Pro | `Win32_OperatingSystem.Caption` |
| Windows version | **25H2** | `HKLM:\…\CurrentVersion\DisplayVersion` |
| Build | **26200** (`10.0.26200`) | `Win32_OperatingSystem.BuildNumber` |
| WSL version | **2.6.3.0** (WSLg 1.0.71) | `wsl --version` |
| WSL kernel | **6.6.87.2-microsoft-standard-WSL2** | `uname -r` |
| WSL distro | **Ubuntu 26.04 LTS** (Resolute Raccoon) | `/etc/os-release` |

---

## AMD Graphics Stack

| Item | Value |
|---|---|
| **GPU driver version** | `32.0.21043.19003` (dated 2026-06-18) |
| **Adrenalin version** | AMD Software: Adrenalin Edition **26.6.2** |
| **Vulkan runtime (loader)** | `vulkan-1.dll` **1.4.309.0** (`C:\Windows\System32`) |
| **Vulkan ICD** | AMD proprietary (shipped with Adrenalin) — llama.cpp reports *"AMD Radeon RX 6900 XT (AMD proprietary driver)"* |
| **Vulkan device caps** | `uma:0  fp16:1  bf16:0  warp size:32  matrix cores: none` (RDNA2 has no WMMA) |
| **HIP SDK** | **7.1.51803** (`C:\Program Files\AMD\ROCm\7.1`, `.hipVersion` githash `d3a86bd04`) |
| **ROCm installs present** | 7.1 only |
| **Driver-shipped HIP runtime** | `amdhip64_6.dll` (HIP **6.x**) in System32/DriverStore |

**Components installed vs used:**

- **Used in production: Vulkan.** All inference goes through `ggml-vulkan.dll`.
- **Installed for experimentation, NOT used: ROCm / HIP SDK 7.1.** The RX 6900 XT is gfx1030
  (RDNA2). `hipGetDeviceCount()` returns **`100` (`hipErrorNoDevice`)** under HIP SDK 7.1, and
  AMD lists only RDNA3/RDNA4 for Windows HIP SDK 7.1 and WSL ROCm (HIP SDK 6.2.4 was the last to
  support this card). The driver-shipped HIP 6.x runtime *can* enumerate the GPU, confirming the
  hardware is fine and the limitation is the support matrix.

> **Production backend = Vulkan. ROCm/HIP = installed for experimentation but NOT used for
> production inference.**

**Re-verify:**
```powershell
(Get-Item C:\Windows\System32\vulkan-1.dll).VersionInfo.ProductVersion       # Vulkan loader
Get-CimInstance Win32_VideoController | ? Name -match Radeon | fl DriverVersion
Get-Content "C:\Program Files\AMD\ROCm\7.1\bin\.hipVersion"
```

---

## AI Software Stack

### llama.cpp

Two builds are present; **production uses Ollama's bundled binary** (it understands the
"Ollama-format" combined qwen2.5-VL GGUF as an `--mmproj`).

| Build | Location | Version | Backend |
|---|---|---|---|
| **Production** | `C:\Users\john\AppData\Local\Programs\Ollama\lib\ollama\llama-server.exe` (+ `vulkan\ggml-vulkan.dll`) | shipped with Ollama 0.30.10 | Vulkan (via `GGML_BACKEND_PATH`) |
| Standalone (experiments) | `C:\ai\llama.cpp\` (`llama-server.exe`, `llama-bench.exe`, …) | **b9821** / build `050ee92d0` (official `llama-*-bin-win-vulkan-x64.zip`) | Vulkan (`ggml-vulkan.dll` co-located) |

> The upstream b9821 `llama-server` **rejects** the combined Ollama qwen2.5-VL blob as
> `--mmproj` (newer llama.cpp expects a *separate* mmproj GGUF). That is why production uses
> Ollama's bundled `llama-server`, which auto-detects and translates the combined blob.

### Ollama

| Item | Value |
|---|---|
| Version | **0.30.10** (client update 0.30.11 available) |
| Install path | `C:\Users\john\AppData\Local\Programs\Ollama` |
| Backend libs | `lib\ollama\{vulkan\ggml-vulkan.dll, rocm_v7_1\, cuda_v12, cuda_v13}` |
| Models directory | `C:\Users\john\.ollama\models` (blobs under `models\blobs\`) |
| Role | Model store + (optional) serving; **must set `OLLAMA_VULKAN=1`** or it falls back to CPU on this card |

### Python

| Environment | Version | Notes |
|---|---|---|
| lawnlord (uv-managed, WSL) | **3.13.13** | `pyproject.toml` → `requires-python = ">=3.13"`; deps via `uv.lock` |
| Key packages (WSL) | duckdb **1.5.3**, pillow **12.2.0**, pypdfium2 | rendering + mirror |
| Windows Python | **3.12.10** | used for benchmark/dump harnesses in `C:\ai` (stdlib `urllib`; PIL only for downscaling) |

**Re-verify:**
```bash
ollama --version
uv run python --version
uv run python -c "import duckdb,PIL; print(duckdb.__version__, PIL.__version__)"
```

---

## Models

| Field | Value |
|---|---|
| **Model name** | `qwen2.5vl:7b` (**production vision model**) |
| Source | Ollama registry (`ollama pull qwen2.5vl:7b`) |
| GGUF / blob | `C:\Users\john\.ollama\models\blobs\sha256-a99b7f834d754b88f122d865f32758ba9f0994a83f8363df2c1e71c17605a025` |
| Quantization | **Q4_K_M** |
| Parameters | 8.3B (architecture `qwen25vl`, embedding length 3584) |
| Context length | 128000 (model max); production uses **8192 per slot** |
| mmproj | **Embedded in the same blob** (pass `--mmproj <same blob>`; server logs *"Ollama-format qwen25vl GGUF used as mmproj; translating"*) |
| Disk size | ≈ **5.56 GiB** (5,969,233,408 bytes) |

Other models present: none required for production. (A text-only `qwen2.5:7b` was used transiently
for a comparison benchmark and is not part of the pipeline.)

**Re-verify:** `ollama show qwen2.5vl:7b`

---

## Production Runtime Configuration

**Server** (Windows host, `scripts/cosmic/serve_vision.cmd 4 2048`):

| Setting | Value | |
|---|---|---|
| `--parallel` (`-np`) | **4** | slots; top of the `-np`/`-ub` sweep within the VRAM budget |
| `-c` | **32768** | = `NP × 8192`; keeps ≥ 8192 ctx/slot for a native 300-DPI page (~5k img tokens) |
| `-ngl` | **99** | all layers on GPU |
| `--flash-attn` | **on** | lower KV memory, faster attention |
| `-b` / `-ub` | **2048 / 2048** | batch / micro-batch — the prefill sweet spot (1024 ~5% slower; 4096 slower *and* hungrier) |
| `--mmproj` | the qwen2.5-VL blob | **projector on GPU** (the key performance win) |
| `--port` / `--host` | 18082 / 127.0.0.1 | loopback (see *Network Layout* for WSL access) |

**Client** (lawnlord, in WSL):

| Setting | Value |
|---|---|
| `--backend` | **llamacpp** |
| `--workers` | **8** (≈ 2 × slots) |

**Input:** native **300 DPI**, 2550×3301 px PNG (`lawnlord explode --dpi 300`; no downscale).

**Expected performance:**

| Metric | Value |
|---|---|
| Throughput | **~24 pages/min** at `-np 4 -ub 2048` (dense pages; faster on the full mix) |
| Peak VRAM | **~11 GB** of 16 GB (whole sweep topped at 11.9 GB) |
| Fidelity | **0.98** self-reported, zero failures |

---

## Environment Variables

| Variable | Value | Scope | Purpose |
|---|---|---|---|
| `OLLAMA_VULKAN` | `1` | User (persisted) | **Required** — without it Ollama tries ROCm (fails on gfx1030) and falls back to CPU (~8 tok/s). Enables the Vulkan backend. |
| `OLLAMA_NUM_PARALLEL` | `4` | User (persisted) | Ollama slot count *when Ollama is the server*. Keep ≤ 4 — NP=8 OOMs at 300 DPI. (Not used by the standalone llama.cpp server, which sets `--parallel` directly.) |
| `OLLAMA_HOST` | `0.0.0.0:11434` | User (persisted) | Binds Ollama on all interfaces so WSL can reach it at the host IP. |
| `GGML_BACKEND_PATH` | `…\Ollama\lib\ollama\vulkan\ggml-vulkan.dll` | Per-process (set by `serve_vision.cmd`) | Forces the standalone `llama-server` onto the **Vulkan** backend (the raw binary won't auto-discover it). |
| `GGML_VK_VISIBLE_DEVICES` | `0` | Per-process | Selects the RX 6900 XT (Vulkan device 0). |
| *(client)* `OLLAMA_HOST` / `--llamacpp-host` | see *Network* | lawnlord | Points lawnlord at the right server from WSL. |

**Re-verify:**
```powershell
[Environment]::GetEnvironmentVariable('OLLAMA_VULKAN','User')
[Environment]::GetEnvironmentVariable('OLLAMA_NUM_PARALLEL','User')
[Environment]::GetEnvironmentVariable('OLLAMA_HOST','User')
```

---

## Network Layout

The model server runs on the **Windows host**; lawnlord runs in **WSL2** and reaches it over
HTTP. WSL sees the Windows host at **`172.31.128.1`** (the default gateway; verify with
`ip route | awk '/default/{print $3}'`).

```
┌──────────────── Windows host ────────────────┐
│                                               │
│  llama-server.exe (standalone, Vulkan)        │
│     listens on 127.0.0.1:18082  ──┐           │
│                                   │           │
│  ollama serve (optional)          │           │
│     listens on 0.0.0.0:11434  ──┐ │           │
│                                 │ │           │
│        RX 6900 XT  ◀── Vulkan ──┘ │           │
└─────────────────────────────────┼─┼──────────┘
                                   │ │  HTTP
                 172.31.128.1:11434│ │127.0.0.1:18082
                                   ▼ ▼
┌──────────────────── WSL2 (Ubuntu) ───────────┐
│  lawnlord transcribe                          │
│    --backend llamacpp  --workers 8            │
│    --llamacpp-host http://<host>:18082         │
└───────────────────────────────────────────────┘
```

| Service | Bind | Port | Reach from WSL |
|---|---|---|---|
| Ollama | `0.0.0.0` | **11434** | `http://172.31.128.1:11434` |
| llama-server (vision) | `127.0.0.1` (default) | **18082** | *loopback only* — for WSL access, start it on `0.0.0.0` and use `http://172.31.128.1:18082`, **or** run the lawnlord client on Windows |

> The production server defaults to loopback. To drive it from WSL, either bind `--host 0.0.0.0`
> in `serve_vision.cmd` and pass `--llamacpp-host http://172.31.128.1:18082`, or run the
> transcribe client with Windows Python. Loopback-only is the safer default when not needed.

---

## Repository / Filesystem Layout

| Path | Contents |
|---|---|
| `~/workspace/lawnlord` (WSL: `/home/john/workspace/lawnlord`) | **Project root** — `src/lawnlord/`, `intake/`, `extracted/pages/`, `lawnlord.duckdb`, `docs/` |
| `…/docs/performance/native-300dpi-vulkan-benchmark.md` | Benchmark study (this machine) |
| `…/docs/reference/development-machine.md` | This document |
| `…/scripts/llamacpp_server.sh` | **cosmos/CUDA/Linux** vision-server profile (does **not** apply to cosmic) |
| `…/scripts/cosmic/` | **Vaulted copies** of the cosmic Windows tooling below (version-controlled source of truth — run them from `C:\ai\` or in place) |
| `C:\ai\` | Inference scratch on the Windows host: |
| `C:\ai\llama.cpp\` | standalone llama.cpp **b9821** win-vulkan build |
| `C:\ai\serve_vision.cmd` | **cosmic vision-server launcher** (Ollama binary + Vulkan + GPU mmproj) |
| `C:\ai\bench.py` | apples-to-apples benchmark harness (both backends) |
| `C:\ai\dump.py` | prints actual transcription text per page (content sanity check) |
| `C:\ai\vram_peak.ps1`, `vram_log.ps1`, `gpubusy.ps1`, `gpumon.ps1` | GPU/VRAM/CPU monitors |
| `C:\ai\bench_pages\`, `bench_1568\`, `bench_1064\` | staged benchmark pages at various resolutions |
| `C:\Users\john\.ollama\models\` | Ollama model store (GGUF blobs) |
| `C:\Users\john\AppData\Local\Programs\Ollama\` | Ollama install (binary + `lib\ollama\` backends) |
| `C:\Program Files\AMD\ROCm\7.1\` | HIP SDK 7.1 (experimentation only) |

---

## Monitoring

`rocm-smi` is **not** available on Windows. Use Windows performance counters.

**VRAM (dedicated usage, MiB):**
```powershell
((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples |
  Measure-Object CookedValue -Maximum).Maximum/1MB
```
Peak sampler: `C:\ai\vram_peak.ps1 -Seconds 40`. Continuous logger: `C:\ai\vram_log.ps1`.

**GPU utilization (% — sum across engines; trust peaks, the counter samples slowly):**
```powershell
((Get-Counter '\GPU Engine(*)\Utilization Percentage').CounterSamples |
  Measure-Object CookedValue -Sum).Sum
```
Helper: `C:\ai\gpubusy.ps1 -Seconds 30` (peak + avg).

**CPU:** `Get-Counter '\Processor(_Total)\% Processor Time'` (should stay low — GPU-bound).

**Throughput / liveness:**
- `GET http://127.0.0.1:18082/health` → `{"status":"ok"}`
- Server log: watch for `ErrorOutOfDeviceMemory` and `exit 99` (→ reduce load / reboot).
- `ollama ps` (if using Ollama) must show **`100% GPU`**, not `100% CPU`.

---

## Reproducing the Environment

Assumes a fresh AMD workstation with an RDNA2/RDNA3 Radeon and the same goal.

1. **BIOS.** Update to a current AGESA, **enable DOCP/XMP** for rated RAM speed, confirm the
   8-pin EPS and GPU power cables are fully seated.
2. **Windows 11 Pro** (25H2+). Install **AMD Adrenalin** (this machine: 26.6.2). Verify the GPU
   in Device Manager and that `vulkan-1.dll` exists in `System32`.
3. **WSL2.** `wsl --install`, install **Ubuntu**, confirm `wsl --version` ≥ 2.x and `/dev/dxg`
   exists in the distro (`ls -l /dev/dxg`).
4. **Tooling in WSL.** Install `uv`; clone lawnlord; `uv sync` (Python ≥ 3.13).
5. **Ollama** (Windows). Install; `ollama pull qwen2.5vl:7b`. Set persistent env:
   ```powershell
   setx OLLAMA_VULKAN 1
   setx OLLAMA_NUM_PARALLEL 4
   setx OLLAMA_HOST 0.0.0.0:11434
   ```
   Restart Ollama; confirm `ollama ps` shows `100% GPU` for a test prompt.
6. **Standalone llama.cpp (optional but recommended for vision).** Either reuse Ollama's bundled
   `llama-server.exe` (as `serve_vision.cmd` does) or download the official
   `llama-*-bin-win-vulkan-x64.zip` into `C:\ai\llama.cpp`.
7. **Scratch dir.** Recreate `C:\ai\` with `serve_vision.cmd`, `bench.py`, and the monitor
   scripts (contents in this repo's docs / `C:\ai`).
8. **Render input.** In WSL: `uv run lawnlord import <bundle.zip>` then
   `uv run lawnlord explode --dpi 300`.
9. **Start the vision server.** On Windows: `scripts/cosmic/serve_vision.cmd 4 2048`. Confirm
   health and that the log shows `offloaded NN/NN layers to GPU` and `CLIP using Vulkan0 backend`.
10. **Warm it** (first batch is ~10× slow), then run `lawnlord transcribe --backend llamacpp
    --workers 8` (wire networking per *Network Layout*).
11. **(Do NOT)** rely on ROCm/HIP for gfx1030 — it will fail enumeration. Vulkan only.

---

## Validation Checklist

Run top-to-bottom; each should pass before declaring the machine production-ready.

- [ ] **GPU detected** — `Get-CimInstance Win32_VideoController | ? Name -match Radeon` shows the RX 6900 XT, Status OK.
- [ ] **Vulkan working** — `C:\ai\llama.cpp\llama-cli.exe --list-devices` lists `Vulkan0: AMD Radeon RX 6900 XT (16368 MiB …)`.
- [ ] **Driver/loader sane** — driver `32.0.21043.x`+, `vulkan-1.dll` ProductVersion ≥ 1.4.x.
- [ ] **Ollama on GPU** — `OLLAMA_VULKAN=1` set; a test generation shows `ollama ps` = `100% GPU`, ~85+ tok/s (not ~8 tok/s CPU).
- [ ] **llama-server starts** — `serve_vision.cmd 4 2048` reaches `server is listening on http://127.0.0.1:18082`; `/health` = `{"status":"ok"}`.
- [ ] **Model loads** — log shows `offloaded 29/29 layers to GPU`, `Vulkan0 model buffer ≈ 4168 MiB`.
- [ ] **mmproj loads on GPU** — log shows `Ollama-format qwen25vl GGUF used as mmproj; translating` and `CLIP using Vulkan0 backend`.
- [ ] **lawnlord connects** — `lawnlord transcribe --backend llamacpp …` returns valid JSON `{transcription, fidelity}` for a page.
- [ ] **Content is real** — `C:\ai\dump.py` shows non-empty transcriptions (hundreds of chars/page), not blanks.
- [ ] **Production benchmark passes** — `-np 4 -ub 2048 / workers 8`, native 300 DPI: **0 failures**, fidelity ≥ 0.95.
- [ ] **Expected throughput achieved** — **~24 pages/min**, peak VRAM **≤ 12 GB** (hard stop at 15 GB).
- [ ] **Stability** — no `exit 99` / `ErrorOutOfDeviceMemory` during a sustained run (if seen: reboot to clear the Vulkan runner, then retest).

---

*See also:* [`docs/performance/native-300dpi-vulkan-benchmark.md`](../performance/native-300dpi-vulkan-benchmark.md)
(the benchmark study and rationale behind every production setting above).
