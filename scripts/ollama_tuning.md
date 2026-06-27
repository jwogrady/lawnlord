# Ollama server tuning (efficiency under load)

These settings live on the **`ollama serve` process**, not the client, so they
go in the systemd drop-in and need a restart. `lawnlord` (the client) can't set
them — passing `OLLAMA_*` to the CLI does nothing.

Targets a single 10 GB RTX 3080 running the lawnlord model-major transcribe.

> Note: `NUM_PARALLEL=6` here is specific to this 10 GB RTX 3080 (a GPU case). It differs from
> `scripts/ollama-override.conf` (`NUM_PARALLEL=1`, the Ryzen CPU-projector case) by hardware
> target, not by contradiction. See `docs/reference/multi-machine-setup.md` for the per-machine model.

| Env var | Value | Why |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `6` | Six requests batched concurrently — keeps the SMs fed without overcommitting VRAM. Measured: 8 slots × 8192 ctx = 65,536-token KV cache pushed ~2 GB past the 10 GB card and Ollama offloaded 17% of the model to CPU (slower). 6 is the most that stays 100% GPU here; confirm with `ollama ps` showing `100% GPU`. If it still spills, drop to 4. |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Model-major: keep exactly one model in VRAM and evict cleanly on switch — never two 6 GB models fighting over 10 GB. |
| `OLLAMA_FLASH_ATTENTION` | `1` | Memory-efficient attention; shrinks the KV cache so `num_ctx × parallel` fits with headroom. |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Quantize the KV cache (~half the memory) — more room for context/parallelism. Requires flash attention. |
| `OLLAMA_KEEP_ALIVE` | `30m` | Don't unload the model between pages during a sweep. |

## Apply

```bash
sudo install -d /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_NUM_PARALLEL=6"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_KEEP_ALIVE=30m"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

## Verify

```bash
# env actually applied to the running server
sudo cat /proc/$(pgrep -x ollama)/environ | tr '\0' '\n' | grep OLLAMA_
# during a run: one model, 100% GPU, flash/kv settings honored
ollama ps
nvidia-smi -l 1
```
