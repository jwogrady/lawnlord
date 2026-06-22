# ADR-0002: Local inference runtime & model under 10 GB WSL2

Status: Proposed
Date: 2026-06-22

## Context

ADR-0001 commits to a local vision backend. The host is an RTX 3080 with **10 GB
total / ~8.7 GB usable** after the WSL2 display reservation, CUDA 13.2. The
backend must run a **document-grade vision-language model** (transcribe a page
PNG → verbatim text + a fidelity estimate), fit that VRAM, install cleanly under
WSL2 GPU paravirtualization, and not become a heavy operational burden for a
single-case tool.

## Decision

Serve the local model with **Ollama**, defaulting to a **Qwen2.5-VL** vision
model sized to fit (7B at 4-bit ≈ 6 GB, with the 3B variant as the headroom
fallback). The model id is a `--model`-style config with a documented default;
the backend talks to Ollama's local HTTP API.

- Ollama installs cleanly in WSL2, detects the paravirtualized GPU, manages
  quantized GGUF weights, and exposes a stable local API — minimal ops for a
  single-case tool.
- Qwen2.5-VL is strong on dense document/OCR-style pages and returns structured
  text reliably, which suits verbatim court-filing transcription.
- The page-at-a-time image budget keeps VRAM within ~8.7 GB.

## Consequences

- **Easier:** zero per-page cost; offline; swappable model behind one flag;
  Ollama handles weight download and GPU placement.
- **Harder:** Ollama must be installed/running as an external local service —
  the backend must detect its absence and fall back to cloud (ADR-0001) with a
  clear message. Exact model fit and fidelity must be confirmed empirically on
  this case's pages (the measurement issue).
- **Tradeoff:** a 4-bit 7B model trades some accuracy for fit; the
  fidelity-gated escalation to Opus (ADR-0001) is what absorbs that on hard
  pages.

## Alternatives considered

- **vLLM.** Faster serving and better batching, but heavier to run and tight at
  10 GB for a 7B vision model; more setup than a single-case tool warrants.
- **llama.cpp directly / transformers + bitsandbytes.** More control, but more
  glue code and weight/GPU management we'd own instead of Ollama.
- **Local OCR (PaddleOCR/docTR) as the primary local tier.** Fits trivially and
  is fast, but the project already established AI transcription is *materially
  more accurate than OCR* (F4 rationale). Reserved at most as a future cheap
  pre-pass, not the default tier.
