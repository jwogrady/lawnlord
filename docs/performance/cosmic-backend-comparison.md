# cosmic backend comparison — llama.cpp/Vulkan vs Ollama (and the ROCm/HIP dead end)

**Machine:** `cosmic` (AMD Radeon RX 6900 XT, RDNA2/gfx1030, 16 GB; Windows 11 + WSL2).
**Question:** for local vision transcription of native 300-DPI court pages, which backend is
faster/better on this card — and what about ROCm? **Bottom line: the standalone llama.cpp
`llama-server` on Vulkan (projector on GPU) is ~10× the throughput of the Ollama `--backend local`
path *and* keeps full 300-DPI fidelity. ROCm/HIP does not work on this GPU at all.**

> **Provenance.** llama.cpp/Vulkan numbers are **measured this session** (2026-06-26 `-np`/`-ub`
> sweep; see [`native-300dpi-vulkan-benchmark.md`](native-300dpi-vulkan-benchmark.md) and the raw
> outputs in [`../../scripts/cosmic/`](../../scripts/cosmic/)). The Ollama-path numbers are from
> **prior characterization** (the benchmark doc's reference table and the notes baked into
> `scripts/transcribe_local.sh`), **not re-measured head-to-head this session** — labeled
> *(documented)* below. A matched A/B is one command away — see *Re-measuring*.

---

## The two backends

| | **llama.cpp / Vulkan** (`--backend llamacpp`) | **Ollama** (`--backend local`) |
|---|---|---|
| Server | standalone `llama-server.exe` (Ollama's bundled build) on Vulkan, `scripts/cosmic/serve_vision.cmd 4 2048` | `ollama serve` on the Windows host (`OLLAMA_VULKAN=1`) |
| Driven by | manual launch + `lawnlord transcribe --backend llamacpp --workers 8` | `scripts/transcribe_local.sh` (+ `.env` / `profiles/cosmic-amd.env`) |
| Image sent | **native 300 DPI** (2550×3301), no downscale | **downscaled to ~1500 px** (qwen default in `transcribe.py`) |
| Vision projector (mmproj) | **on GPU** (the key win) | **on CPU** (`--no-mmproj-offload`) — the bottleneck |
| Slots / parallel | `-np 4`, `-c 32768` | `OLLAMA_NUM_PARALLEL` (≤ 4 here; vision serializes) |

---

## Results

| Metric | llama.cpp / Vulkan (measured) | Ollama `--backend local` *(documented)* |
|---|---|---|
| **Throughput** | **24.2 pages/min** (`-np 4 -ub 2048`) | **~2–3 pages/min** (~30 s/page, CPU image-encode) |
| Relative | **~10× faster** | baseline |
| Input resolution | **native 300 DPI** (full fidelity) | 1500 px downscale (text legible, but lossy) |
| Self-reported fidelity | **0.98**, 0 failures | comparable on printed text at 1500 px; loses fine detail |
| Peak VRAM | ~11 GB of 16 GB | lower (model only; encode is on CPU) |
| GPU utilisation | ~96% (encode + decode on GPU) | low GPU / **high CPU** (encode is CPU-bound) |

**Why the gap:** the cost driver for these pages is the **vision prefill (image encode)**, not
token generation. llama.cpp runs that encode **on the GPU** over the **full-resolution** image;
Ollama's local path runs it **on the CPU** over a **downscaled** image. So llama.cpp is both faster
*and* higher-fidelity — the usual speed/quality trade-off does not apply here.

**When the Ollama path is still useful:** quick smoke tests, or when the standalone server isn't
running. It's the *secondary* path on cosmic, not the production one.

---

## The ROCm / HIP dead end (why Vulkan at all)

We installed the AMD **HIP SDK 7.1** (`C:\Program Files\AMD\ROCm\7.1`) intending to run ROCm/HIP
as the fast path. It does **not** work on this GPU:

- The RX 6900 XT is **gfx1030 / RDNA2**. `hipGetDeviceCount()` returns **`100` (`hipErrorNoDevice`)**
  under HIP SDK 7.1. AMD lists only **RDNA3/RDNA4** for Windows HIP SDK 7.1 and WSL ROCm; HIP SDK
  **6.2.4** was the last to support this card.
- The driver-shipped HIP **6.x** runtime *can* enumerate the GPU, proving the hardware is fine —
  the limitation is purely AMD's support matrix.
- **Conclusion: ROCm/HIP is not a production option on gfx1030. Vulkan is the path.** The HIP SDK
  7.1 install is harmless to leave for experimentation but is **unused**; it can be uninstalled
  without affecting the Vulkan production path.

Also load-bearing for Vulkan to actually engage: **`OLLAMA_VULKAN=1`** must be set, or Ollama
tries ROCm, fails, and silently falls back to CPU (~8 tok/s).

---

## Re-measuring (matched head-to-head)

To replace the *(documented)* Ollama figures with a fresh matched run on the same pages:

```bash
# Windows-side, with ollama serve up (OLLAMA_VULKAN=1) and the vision server down:
python scripts/cosmic/bench.py ollama   http://127.0.0.1:11434 1500 C:\ai\bench_pages 4
# vs the production llama.cpp path:
python scripts/cosmic/bench.py llamacpp http://127.0.0.1:18082 0    C:\ai\bench_pages 8
```
Compare `PAGES/MIN`, `avg fid`, and failures. (Bench inputs are case-page renders and live only on
the machine — never commit them.)

*See also:* [`native-300dpi-vulkan-benchmark.md`](native-300dpi-vulkan-benchmark.md) ·
[`../reference/development-machine.md`](../reference/development-machine.md) ·
[`../reference/multi-machine-setup.md`](../reference/multi-machine-setup.md)
