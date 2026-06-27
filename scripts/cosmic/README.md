# `scripts/cosmic/` — AMD/Vulkan vision-server tooling (the **cosmic** workstation)

These run **Windows-side** on `cosmic` (AMD Radeon RX 6900 XT, RDNA2/gfx1030), where local
multimodal inference goes through **llama.cpp on the Vulkan backend** (ROCm/HIP does not support
this card — see [`docs/reference/development-machine.md`](../../docs/reference/development-machine.md)).
lawnlord itself runs in WSL2 and talks to the server over HTTP.

> **These are the live working copies vaulted from `C:\ai\` so the setup survives a machine wipe.**
> They assume the scratch layout `C:\ai\` and Ollama installed at the default user path. Paths are
> baked in — adjust the `set` lines / globs if your layout differs. They do **not** belong to the
> Python package; nothing in `src/lawnlord/` imports them.

## Production launch

```bat
:: on Windows (cmd), from C:\ai (or wherever these live)
serve_vision.cmd 4 2048      :: -np 4 -c 32768 --flash-attn on -b 2048 -ub 2048  (the sweep winner)
```
Then drive it from WSL:
```bash
uv run lawnlord transcribe --backend llamacpp --workers 8 \
  --llamacpp-host http://<windows-host>:18082 --model qwen2.5vl:7b
```

## Files

| File | What it does |
|---|---|
| `serve_vision.cmd` | Launches Ollama's bundled `llama-server.exe` on **Vulkan** with the qwen2.5-VL projector **on the GPU**. Args: `[NP] [UBATCH]`, default `4 2048` (the benchmarked production point). |
| `transcribe_vision.sh` | **WSL-side fast-path runner.** Preflights the :18082 Vulkan server and **fails loudly if it's down** (instead of silently dropping to the ~100-min Ollama path), then runs `lawnlord transcribe --backend llamacpp --workers 8`. This is the ~10-min job for the 255-page case. |
| `bench.py` | Apples-to-apples throughput/fidelity harness for **both** backends: `python bench.py {llamacpp\|ollama} <host> <maxpx:0=native> <pagedir> <workers>`. Prints pages/min, gen tok/s, fidelity, failures. |
| `dump.py` | Prints the actual transcription text per page (content sanity check). **Outputs case text — do not redirect into the repo.** |
| `sweep.ps1` | Drives the full `-np`/`-ub` sweep (restart → warm → measure → VRAM peak per config) → `sweep_results.txt`. |
| `vram_peak.ps1` / `vram_log.ps1` | Peak / continuous VRAM samplers (Windows GPU perf counters; `rocm-smi` is unavailable on Windows). |
| `gpubusy.ps1` / `gpumon.ps1` | GPU-utilisation / combined monitors. |
| `prompt.txt` | The transcription prompt used by the harnesses. |
| `sweep_results.txt`, `bench_np*.out` | Captured results from the 2026-06-26 sweep (evidence behind the benchmark doc). |

## Results behind these (2026-06-26 sweep)

Winner **`-np 4 -ub 2048` → 24.2 pages/min**, fidelity 0.98, ~11 GB peak VRAM, native 300 DPI.
Full study: [`docs/performance/native-300dpi-vulkan-benchmark.md`](../../docs/performance/native-300dpi-vulkan-benchmark.md).
Backend A/B (Vulkan vs Ollama): [`docs/performance/cosmic-backend-comparison.md`](../../docs/performance/cosmic-backend-comparison.md).

> The Linux/CUDA equivalent for the **cosmos** (NVIDIA) box is `scripts/llamacpp_server.sh`.
