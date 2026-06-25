"""Transcribe each filed page from its PNG render using Claude vision (F4).

PNG-per-page → AI transcription (measured materially more accurate than OCR).
This is the **additive** text layer on the Exploded view: it reads the `pages`
table's PNGs and appends to `page_text` — rev 0 is the original transcription
(immutable); a re-run appends a new revision, never overwriting. Each row carries
a **fidelity** signal (the model's self-assessment of how completely it could read
the page) — the honest reframing of the removed page-score (#70).

Cloud opt-in: the CLI runs this only when ``ANTHROPIC_API_KEY`` is set. The
Anthropic client is injectable so tests mock it (no network in CI).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Protocol

import duckdb
import pypdfium2 as pdfium

# Per-run file logger (configured by logging_setup at run start). Records here
# are additive to the Rich console: they capture the per-page failures the
# passes below otherwise swallow (reason, model, exception/traceback). Until a
# run installs a FileHandler, these records go nowhere — harmless.
_log = logging.getLogger("lawnlord.transcribe")

# Below this many non-whitespace characters, a page's embedded text layer is
# treated as absent (scanned/image-only) and the page falls through to the
# vision tier. The working case shows a clean gap around here — pages carry
# either <54 chars (stamps on image pages) or >=100 (born-digital text), nothing
# between — so the exact cutoff in (53, 100] is not sensitive.
MIN_PDF_TEXT_CHARS = 100

# Vision-tier concurrency. Only the network-bound model calls run in the pool;
# the local pre-pass and every DuckDB write stay on the calling thread (a DuckDB
# connection is single-threaded), so insert order stays deterministic.
DEFAULT_WORKERS = 8

# Retry the vision call on transient API errors, with exponential backoff.
_RETRY_ATTEMPTS = 4
_RETRY_BASE_DELAY = 1.0
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 529})

# Claude vision model. Confirmed current via the claude-api reference; override
# with --model. Adaptive thinking is off by default on this model (omitted).
DEFAULT_MODEL = "claude-opus-4-8"

# Structured output: the model returns the page text + a 0..1 fidelity estimate.
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "transcription": {"type": "string"},
        "fidelity": {"type": "number"},
    },
    "required": ["transcription", "fidelity"],
    "additionalProperties": False,
}

_PROMPT = (
    "Transcribe this filed court document page verbatim — preserve the wording, "
    "line breaks, and reading order; do not summarize, correct, or omit anything. "
    "Return JSON with `transcription` (the full page text) and `fidelity` (0.0–1.0: "
    "your confidence the transcription is complete and accurate given how legible "
    "the image is)."
)

# The single append-only write into page_text, shared by the transcribe and
# escalate passes (rev 0 of a variation immutable; every pass appends the next
# rev within that variation). The surrogate `id` (ADR-0005) is computed via
# `_row_id` so each (page_id, source, model, rev) variation is addressable.
_PAGE_TEXT_INSERT = (
    "INSERT INTO page_text (id, case_id, page_id, rev, source, text, fidelity, "
    "model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _row_id(page_id, source, model, rev) -> str:
    """Stable surrogate id for one transcription variation: a content hash of
    ``(page_id, source, model, rev)``. `model` is null for ``pdf_text``. Same
    inputs → same id, so re-inserting an identical variation conflicts (rev 0
    immutable) and the mirror stays deterministic."""
    digest = hashlib.sha256(
        f"{page_id}|{source}|{model or ''}|{rev}".encode()
    ).hexdigest()
    return "pt_" + digest[:16]


def make_client():
    """The default Anthropic client (reads ANTHROPIC_API_KEY from the env)."""
    import anthropic

    return anthropic.Anthropic()


def _b64_png(path: str | Path) -> str:
    return base64.standard_b64encode(Path(path).read_bytes()).decode("utf-8")


def transcribe_page(png_path: str | Path, client, model: str = DEFAULT_MODEL) -> dict:
    """Transcribe one page PNG via Claude vision. ``client`` is any object with an
    ``messages.create`` compatible with the Anthropic SDK (injected for tests).
    Returns ``{text, fidelity, model}``."""
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": _b64_png(png_path),
                        },
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
    )
    text = next(b.text for b in resp.content if getattr(b, "type", None) == "text")
    # A response that ended because it hit max_tokens is truncated: its JSON may
    # not even close, so a bare json.loads would raise. Salvage any partial
    # transcription text (mirroring the local tier) and force fidelity to 0.0 —
    # same handling as the llama.cpp tier's finish_reason=='length' — so the
    # incomplete reading still lands a row, but below FIDELITY_FLAG_THRESHOLD and
    # into the flagged-page worklist rather than being silently trusted or dropped.
    if getattr(resp, "stop_reason", None) == "max_tokens":
        result = _parse_local_output(text, model)
        result["fidelity"] = 0.0
        return result
    data = json.loads(text)
    return {
        "text": data.get("transcription", ""),
        "fidelity": float(data.get("fidelity", 0.0)),
        "model": model,
    }


# Local vision tier (ADR-0002): a vision model served by Ollama on the GPU.
# No per-page cost, no rate limit, no data leaving the machine.
DEFAULT_LOCAL_MODEL = "qwen2.5vl:7b"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
# Standalone llama.cpp server (scripts/llamacpp_server.sh) with the vision
# projector ON the GPU — ~10x faster prefill than Ollama's CPU mmproj, so the
# native 300-DPI render is fast. OpenAI-compatible API. See memory:
# ollama-vision-cpu-bottleneck.
DEFAULT_LLAMACPP_HOST = "http://localhost:18082"
# Ollama defaults a model's context to 4096 tokens. A high-DPI page render
# tokenizes to more than that on its own (a 300-DPI page is ~4100 vision tokens
# for qwen2.5-vl), so without an explicit window every such page 400s with
# "exceeds the available context size" and the whole local tier silently fails.
# 8192 fits a 300-DPI page with headroom; override per backend if needed.
DEFAULT_NUM_CTX = 8192

# Per-local-model tuning, keyed by name prefix so tag variants (``:latest``,
# ``:7b``) match. Vision encoders differ wildly on the SAME page render, so a
# single setting can't serve all of them:
#   * num_ctx     — token window (Ollama defaults to 4096; high-DPI pages overflow it).
#   * max_image_px — longest side to downscale the page to before sending. granite's
#                    encoder turns a 300-DPI page into ~73k tokens, so its input must
#                    be capped; qwen reads the native render fine (best fidelity).
#   * num_predict — cap on generated tokens. minicpm-v ignores the JSON stop and
#                    rambles to the context limit, so bound it and salvage the text.
_DEFAULT_TUNING: dict[str, int | None] = {
    "num_ctx": DEFAULT_NUM_CTX, "max_image_px": None, "num_predict": -1,
}
_LOCAL_TUNING: dict[str, dict[str, int | None]] = {
    # Ollama runs the vision projector on CPU (--no-mmproj-offload), so per-page
    # cost is the CPU image-encode and scales ~linearly with image tokens. A
    # 300-DPI page (~4100 tokens) is ~64 s; 1500 px (~1800 tokens) is ~24 s with
    # identical printed text (only faint stamps differ). So qwen reads at 1500 px
    # by default — reserve native 300 DPI for retry/exception pages via
    # --max-image-px 0. See memory: ollama-vision-cpu-bottleneck.
    "qwen2.5vl":         {"num_ctx": 8192,  "max_image_px": 1500, "num_predict": -1},
    "granite3.2-vision": {"num_ctx": 16384, "max_image_px": 1024, "num_predict": -1},
    "minicpm-v":         {"num_ctx": 8192,  "max_image_px": None, "num_predict": 2048},
}


def _tuning_for(model: str) -> dict[str, int | None]:
    for prefix, tuning in _LOCAL_TUNING.items():
        if model.startswith(prefix):
            return tuning
    return _DEFAULT_TUNING


def _b64_png_scaled(path: str | Path, max_px: int | None) -> str:
    """Base64 PNG, downscaled so the longest side is at most ``max_px`` (keeping
    aspect). ``None`` or an already-small image sends the native render."""
    if not max_px:
        return _b64_png(path)
    from io import BytesIO

    from PIL import Image

    im: Image.Image = Image.open(path)
    longest = max(im.size)
    if longest <= max_px:
        return _b64_png(path)
    scale = max_px / longest
    im = im.resize((round(im.width * scale), round(im.height * scale)))
    buf = BytesIO()
    im.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def _parse_local_output(content: str, model: str) -> dict:
    """Turn an Ollama message body into ``{text, fidelity, model}``. The happy
    path is the structured JSON the schema requests; when a model emits invalid
    or truncated JSON (e.g. minicpm-v running past its stop), salvage the
    transcription text and flag it with ``fidelity=0.0`` so the divergence
    metrics treat it as the low-confidence reading it is."""
    try:
        data = json.loads(content)
        return {
            "text": data.get("transcription", ""),
            "fidelity": float(data.get("fidelity", 0.0)),
            "model": model,
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        import re

        m = re.search(r'"transcription"\s*:\s*"', content)
        if not m:
            return {"text": content.strip(), "fidelity": 0.0, "model": model}
        tail = content[m.end():]
        cut = re.search(r'"\s*,\s*"fidelity"', tail)  # closed string → cut at it
        tail = tail[: cut.start()] if cut else tail.rstrip().rstrip("}").rstrip().rstrip('"')
        try:  # decode JSON string escapes (\n, \", …) best-effort
            text = json.loads('"' + tail + '"')
        except json.JSONDecodeError:
            text = tail.replace('\\n', '\n').replace('\\"', '"')
        return {"text": text, "fidelity": 0.0, "model": model}


class Transcriber(Protocol):
    """A vision backend: turn a page PNG into ``{text, fidelity, model}``.

    Generalizes the injectable seam — ``transcribe_case`` calls ``.transcribe``
    and is agnostic to whether the text came from the cloud or a local model."""

    model: str

    def transcribe(self, png_path: str | Path) -> dict: ...


class CloudTranscriber:
    """Vision tier backed by Claude (the Anthropic API). Wraps the injectable
    ``client`` so tests mock it; defaults to a real client from the env key."""

    def __init__(self, client=None, model: str = DEFAULT_MODEL):
        self._client = client if client is not None else make_client()
        self.model = model

    def transcribe(self, png_path: str | Path) -> dict:
        return transcribe_page(png_path, self._client, model=self.model)


class LocalTranscriber:
    """Vision tier backed by a local Ollama vision model — free, offline, and
    the page never leaves the machine. Talks to Ollama's HTTP API via the stdlib
    (no new dependency); a failure here propagates so the caller can record it."""

    def __init__(self, model: str = DEFAULT_LOCAL_MODEL, host: str | None = None,
                 max_image_px: int | None = None):
        self.model = model
        self._host = (host or DEFAULT_OLLAMA_HOST).rstrip("/")
        self._tuning = dict(_tuning_for(model))
        # An explicit --max-image-px overrides the per-model default: a positive
        # value caps the longest side, 0 means send the native render (300 DPI).
        if max_image_px is not None:
            self._tuning["max_image_px"] = max_image_px or None

    def transcribe(self, png_path: str | Path) -> dict:
        import urllib.request

        t = self._tuning
        options = {"temperature": 0, "num_ctx": t["num_ctx"]}
        if t["num_predict"] and t["num_predict"] > 0:
            options["num_predict"] = t["num_predict"]
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "user", "content": _PROMPT,
                 "images": [_b64_png_scaled(png_path, t["max_image_px"])]}
            ],
            "stream": False,
            "format": _OUTPUT_SCHEMA,
            "options": options,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self._host}/api/chat", data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read())
        return _parse_local_output(body["message"]["content"], self.model)


class LlamaCppTranscriber:
    """Vision tier backed by a standalone llama.cpp server with the multimodal
    projector ON the GPU (unlike Ollama's ``--no-mmproj-offload``, which strands
    the vision encode on the CPU). Talks to the OpenAI-compatible
    ``/v1/chat/completions`` endpoint with a ``json_schema`` response format, so
    it keeps the same ``{text, fidelity, model}`` contract as the others.

    ~10x faster prefill than the Ollama tier, fast enough that the native
    300-DPI render needs no downscale. Start the server with
    ``scripts/llamacpp_server.sh``."""

    def __init__(self, model: str = DEFAULT_LOCAL_MODEL, host: str | None = None,
                 max_image_px: int | None = None):
        self.model = model
        self._host = (host or DEFAULT_LLAMACPP_HOST).rstrip("/")
        # GPU vision is fast — default to the native render; --max-image-px (a
        # positive value) still downscales, 0 is treated as native.
        self._max_image_px = max_image_px or None

    def transcribe(self, png_path: str | Path) -> dict:
        import urllib.request

        data_uri = "data:image/png;base64," + _b64_png_scaled(png_path, self._max_image_px)
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]}],
            "temperature": 0,
            # Court caption pages have a tall column of "§" dividers; at temp 0
            # the model can fall into a degenerate loop emitting "§" until the
            # token ceiling (finish_reason=length, JSON never closes -> fidelity
            # 0). A mild repeat penalty breaks the loop with no quality cost
            # (verified: fidelity 0.0 -> 0.98). max_tokens is a backstop — a dense
            # legit page is ~1200 tokens, so 3072 never truncates real content.
            "max_tokens": 3072,
            "repeat_penalty": 1.1,
            "repeat_last_n": 64,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "page", "schema": _OUTPUT_SCHEMA, "strict": True}},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self._host}/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read())
        choice = body["choices"][0]
        result = _parse_local_output(choice["message"]["content"], self.model)
        # Safeguard: a page that ended because it hit the token ceiling
        # (finish_reason='length') is truncated/runaway. The model may still
        # self-report high fidelity on text it didn't finish, so force it to 0.0
        # — that drops it below FIDELITY_FLAG_THRESHOLD and into the flagged-page
        # worklist (export-metrics), making the exception visible for review or a
        # higher-budget retry instead of silently trusting incomplete output.
        if choice.get("finish_reason") == "length":
            result["fidelity"] = 0.0
            _log.warning(
                "llamacpp transcription truncated (finish_reason='length'); "
                "forcing fidelity=0.0 model=%s png=%s",
                self.model, png_path,
            )
        return result


def _ollama_tags(host: str | None = None) -> list[dict] | None:
    """The raw ``/api/tags`` model list from the Ollama server, or ``None`` when
    the server is unreachable. Shared by ``ollama_available`` and
    ``installed_vision_models`` so both speak to the same endpoint identically."""
    import urllib.request

    host = (host or DEFAULT_OLLAMA_HOST).rstrip("/")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as resp:
            tags = json.loads(resp.read())
    except Exception as exc:
        _log.warning(
            "Ollama unreachable at %s/api/tags (%s: %s); local tier unavailable",
            host, type(exc).__name__, exc,
        )
        return None
    return tags.get("models", [])


def ollama_available(model: str = DEFAULT_LOCAL_MODEL, host: str | None = None) -> bool:
    """True if the Ollama server is reachable and ``model`` is pulled — the gate
    the CLI uses to decide local vs the cloud fallback."""
    models = _ollama_tags(host)
    if models is None:
        return False
    names = {m.get("name", "") for m in models}
    if model in names or f"{model}:latest" in names:
        return True
    # A bare name (no explicit ``:tag``) matches any pulled tag of that repo; an
    # explicit tag must match exactly — else we'd green-light a tag that isn't
    # pulled and the call would fail at runtime instead of falling back to cloud.
    if ":" not in model:
        return any(n.split(":", 1)[0] == model for n in names)
    return False


def installed_vision_models(host: str | None = None) -> list[str]:
    """Sorted names of pulled Ollama models that advertise ``"vision"`` among
    their ``capabilities`` — the local set the exhaustive transcribe pass runs.
    Returns ``[]`` when the server is unreachable (never raises), so the caller
    degrades to whatever other backends are available."""
    models = _ollama_tags(host)
    if models is None:
        return []
    vision = [
        m.get("name", "")
        for m in models
        if "vision" in (m.get("capabilities") or [])
    ]
    return sorted(n for n in vision if n)


def extract_pdf_text(pdf_path: str | Path) -> list[str]:
    """Embedded text of each page of ``pdf_path`` (list index = 0-based page
    index), read via pypdfium2 — free, deterministic, and the page's *exact* text
    when it is born-digital. A page with no text layer yields an empty/near-empty
    string: the signal that it is scanned/image-only and needs the vision tier."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        texts: list[str] = []
        for i in range(len(pdf)):
            page = pdf[i]
            textpage = page.get_textpage()
            try:
                texts.append(textpage.get_text_range())
            finally:
                textpage.close()
                page.close()
        return texts
    finally:
        pdf.close()


def _is_transient(exc: Exception) -> bool:
    """A vision-call error worth retrying: an HTTP 429/5xx (rate limit /
    overloaded / transient server) or a connection/timeout error — covering both
    the cloud SDK (Anthropic) and the local backend (Ollama over urllib)."""
    import socket
    import urllib.error

    # Anthropic exposes the status as ``.status_code``; urllib's HTTPError as ``.code``.
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    if status in _TRANSIENT_STATUS:
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return False  # a definite non-transient HTTP status (404 model-not-found, 400, …)

    import anthropic

    return isinstance(exc, (
        anthropic.APIConnectionError, anthropic.APITimeoutError,
        urllib.error.URLError, socket.timeout,  # connection refused / read timeout
    ))


def _transcribe_with_retry(
    transcriber: Transcriber, png_path, attempts: int = _RETRY_ATTEMPTS,
    base_delay: float = _RETRY_BASE_DELAY,
) -> dict:
    """``transcriber.transcribe`` with exponential backoff on transient API
    errors. A non-transient error, or the last attempt, re-raises for the caller
    to record."""
    for attempt in range(attempts):
        try:
            return transcriber.transcribe(png_path)
        except Exception as exc:
            transient = _is_transient(exc)
            if attempt + 1 >= attempts or not transient:
                # The error propagates to the caller (which records the page in
                # `failed`); log the exhausted/non-transient cause with model and
                # page so the file accounts for why this attempt gave up.
                _log.warning(
                    "transcribe attempt %d/%d gave up (%s) model=%s png=%s: %s: %s",
                    attempt + 1, attempts,
                    "retries exhausted" if transient else "non-transient error",
                    getattr(transcriber, "model", "?"), png_path,
                    type(exc).__name__, exc,
                )
                raise
            # Exponential backoff with jitter, so concurrent workers don't retry
            # in lockstep against a shared overloaded API.
            delay = base_delay * (2 ** attempt)
            time.sleep(delay * (0.5 + random.random()))
    # Unreachable for attempts >= 1 (the final iteration always returns or
    # raises); guards the degenerate attempts <= 0 call and satisfies the
    # return-type checker.
    raise ValueError(f"attempts must be >= 1, got {attempts}")


def _embedded_text(intake_dir, intake_path, image_id, page_number, cache) -> str | None:
    """Embedded text for one page (1-based ``page_number``) of its source PDF, or
    ``None`` when the pre-pass cannot run (no intake dir, missing or unreadable
    PDF, or index out of range) — in which case the page falls through to the
    vision tier. Caches per-image extraction so each PDF is opened at most once."""
    if intake_dir is None or intake_path is None:
        return None
    if image_id not in cache:
        pdf_path = intake_dir / intake_path
        try:
            cache[image_id] = extract_pdf_text(pdf_path) if pdf_path.exists() else None
        except Exception:
            # A corrupt/encrypted/unreadable PDF has no usable text layer for our
            # purposes: degrade to the vision tier rather than abort the run.
            cache[image_id] = None
    texts = cache[image_id]
    if texts is None:
        return None
    idx = page_number - 1
    return texts[idx] if 0 <= idx < len(texts) else None


def _next_rev(con, page_id, source, model) -> int | None:
    """The next rev to write for one ``(page_id, source, model)`` variation, or
    ``None`` if that variation already exists (caller skips unless forcing).
    ``model`` is null for ``pdf_text`` — matched with ``IS NOT DISTINCT FROM`` so
    NULL compares equal to NULL."""
    prev = con.execute(
        "SELECT max(rev) FROM page_text "
        "WHERE page_id = ? AND source = ? AND model IS NOT DISTINCT FROM ?",
        [page_id, source, model],
    ).fetchone()[0]
    return None if prev is None else prev + 1


def transcribe_case(
    con: duckdb.DuckDBPyConnection,
    pages_dir: str | Path,
    generated_at: str,
    transcriber: Transcriber | list[Transcriber] | tuple[Transcriber, ...],
    force: bool = False,
    intake_dir: str | Path | None = None,
    max_workers: int = DEFAULT_WORKERS,
) -> dict:
    """Transcribe pages in the `pages` table, appending to `page_text`.

    **Exhaustive (ADR-0006):** the corpus holds a reading from *every* available
    backend on *every* page, for comparison — nothing is skipped because another
    reading already exists. **Text-layer pre-pass (ADR-0004):** when ``intake_dir``
    is given and a page is born-digital, its exact text is read straight from the
    PDF (``source='pdf_text'``, ``fidelity=1.0``, no model call) — but this no
    longer short-circuits the vision tier. Then *each* ``transcriber`` (cloud
    and/or local; ADR-0001/0002) transcribes the page (``source='ai'``), needing
    the rendered PNG under ``pages_dir``.

    ``transcriber`` may be a single :class:`Transcriber` or a list of them
    (normalized internally), so a single-backend caller still works.

    The vision calls (network-bound) run concurrently in a bounded pool of
    ``max_workers``, retried with backoff on transient API errors; a unit that
    still fails is reported in ``failed`` rather than aborting the run. Every
    DuckDB write stays on the calling thread, and **each unit is committed the
    moment it finishes** — so an interrupted run keeps what's done and a re-run
    costs only the rest. Output is read back in page/rev order, so completion
    order of the concurrent writes is not observable (ADR-0003).

    Resumable by default, **per ``(page, source, model)`` variation**: a variation
    that already exists is skipped; a re-run fills only the missing ones (e.g. a
    newly-installed model). ``force=True`` appends the next rev within each
    variation (rev 0 stays immutable; revisions are never overwritten).
    """
    transcribers = (
        list(transcriber)
        if isinstance(transcriber, (list, tuple))
        else [transcriber]
    )
    pages_dir = Path(pages_dir)
    intake_dir = Path(intake_dir) if intake_dir is not None else None
    rows = con.execute(
        "SELECT p.id, p.case_id, p.page_image_path, p.image_id, p.page_number, "
        "i.intake_path FROM pages p JOIN images i ON i.id = p.image_id "
        "ORDER BY p.id"
    ).fetchall()

    done = 0
    pdf_text = 0
    fidelity_sum = 0.0
    skipped: list[str] = []
    skipped_existing: list[str] = []
    failed: list[str] = []
    text_cache: dict[str, list[str] | None] = {}

    # Phase 1 (sequential, page order): store the born-digital text layer now
    # (local and free), then queue a vision unit for every transcriber that
    # doesn't yet have a reading of this page. Skip/resume is per variation.
    vision: list[tuple] = []
    for page_id, case_id, rel, image_id, page_number, intake_path in rows:
        # Lever 0: a born-digital page holds its exact text — store it verbatim
        # (fidelity 1.0, no model) as the `pdf_text` variation. Distinct from OCR;
        # see ADR-0004. This no longer short-circuits the vision tier (ADR-0006).
        embedded = _embedded_text(intake_dir, intake_path, image_id, page_number, text_cache)
        if embedded is not None and len(embedded.strip()) >= MIN_PDF_TEXT_CHARS:
            rev = _next_rev(con, page_id, "pdf_text", None)
            if rev is not None and not force:
                skipped_existing.append(page_id)  # variation present → skip
            else:
                rev = 0 if rev is None else rev
                con.execute(_PAGE_TEXT_INSERT, [_row_id(page_id, "pdf_text", None, rev),
                                      case_id, page_id, rev, "pdf_text", embedded,
                                      1.0, None, generated_at])
                pdf_text += 1

        # Vision tier (needs the rendered PNG): queue a unit per transcriber that
        # is missing this page's variation (or forced).
        png = pages_dir / rel
        for tr in transcribers:
            rev = _next_rev(con, page_id, "ai", tr.model)
            if rev is not None and not force:
                skipped_existing.append(page_id)  # this (page, model) already read
                continue
            rev = 0 if rev is None else rev
            if not png.exists():
                skipped.append(rel)
                continue
            vision.append((page_id, case_id, rev, png, tr))

    # Phase 2 (concurrent): the network-bound vision calls. Each result is
    # committed on this thread as its future completes, so progress is durable
    # mid-run; a unit that fails after retries is reported, not dropped.
    if vision:
        workers = max(1, min(max_workers, len(vision)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_unit = {
                pool.submit(_transcribe_with_retry, tr, png):
                    (page_id, case_id, rev, tr.model)
                for (page_id, case_id, rev, png, tr) in vision
            }
            for future in as_completed(future_to_unit):
                page_id, case_id, rev, model = future_to_unit[future]
                try:
                    result = future.result()
                except Exception as exc:
                    failed.append(page_id)
                    _log.error(
                        "transcribe failed page_id=%s rev=%s model=%s: %s: %s",
                        page_id, rev, model, type(exc).__name__, exc,
                        exc_info=exc,
                    )
                    continue
                con.execute(_PAGE_TEXT_INSERT, [_row_id(page_id, "ai", result["model"], rev),
                                      case_id, page_id, rev, "ai", result["text"],
                                      result["fidelity"], result["model"], generated_at])
                done += 1
                fidelity_sum += result["fidelity"]

    return {
        "pages": done,
        "ai": done,
        "pdf_text": pdf_text,
        "avg_fidelity": (fidelity_sum / done) if done else 0.0,
        "skipped": skipped,
        "skipped_existing": skipped_existing,
        "failed": failed,
    }


def escalate_case(
    con: duckdb.DuckDBPyConnection,
    pages_dir: str | Path,
    generated_at: str,
    cloud_transcriber: Transcriber,
    threshold: float,
    max_workers: int = DEFAULT_WORKERS,
) -> dict:
    """Re-transcribe low-fidelity model pages on the cloud tier (ADR-0001).

    Selects pages whose **latest** `page_text` rev is a model transcription
    (``source='ai'``) with ``fidelity < threshold`` — born-digital pages
    (``source='pdf_text'``, fidelity 1.0) are never escalated — and re-transcribes
    each with ``cloud_transcriber``, appending the next rev. Append-only: the
    local attempt is preserved as its own rev. Concurrent + durable like
    :func:`transcribe_case`.
    """
    pages_dir = Path(pages_dir)
    # Latest rev per page; keep only model pages (not pdf_text) below threshold
    # that the cloud tier hasn't already produced — so a genuinely hard page the
    # cloud also reads below T isn't re-escalated (and re-billed) on every run.
    rows = con.execute(
        "SELECT pt.case_id, pt.page_id, pt.rev, p.page_image_path "
        "FROM page_text pt "
        "JOIN pages p ON p.id = pt.page_id "
        "JOIN (SELECT page_id, max(rev) AS mrev FROM page_text GROUP BY page_id) m "
        "  ON m.page_id = pt.page_id AND m.mrev = pt.rev "
        "WHERE pt.source = 'ai' AND pt.fidelity < ? "
        "  AND (pt.model IS NULL OR pt.model != ?) "
        "ORDER BY pt.page_id",
        [threshold, cloud_transcriber.model],
    ).fetchall()

    targets = []
    failed: list[str] = []
    for case_id, page_id, rev, rel in rows:
        png = pages_dir / rel
        if not png.exists():
            failed.append(page_id)
            _log.warning(
                "escalate skipped page_id=%s model=%s: missing page PNG %s",
                page_id, cloud_transcriber.model, png,
            )
            continue
        targets.append((case_id, page_id, rev + 1, png))  # append the next rev

    escalated = 0
    fidelity_sum = 0.0
    if targets:
        workers = max(1, min(max_workers, len(targets)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_page = {
                pool.submit(_transcribe_with_retry, cloud_transcriber, png):
                    (case_id, page_id, rev)
                for (case_id, page_id, rev, png) in targets
            }
            for future in as_completed(future_to_page):
                case_id, page_id, rev = future_to_page[future]
                try:
                    result = future.result()
                except Exception as exc:
                    failed.append(page_id)
                    _log.error(
                        "escalate failed page_id=%s rev=%s model=%s: %s: %s",
                        page_id, rev, cloud_transcriber.model,
                        type(exc).__name__, exc, exc_info=exc,
                    )
                    continue
                con.execute(_PAGE_TEXT_INSERT, [_row_id(page_id, "ai", result["model"], rev),
                            case_id, page_id, rev, "ai",
                            result["text"], result["fidelity"], result["model"],
                            generated_at])
                escalated += 1
                fidelity_sum += result["fidelity"]

    return {
        "candidates": len(rows),
        "escalated": escalated,
        "avg_fidelity": (fidelity_sum / escalated) if escalated else 0.0,
        "failed": failed,
    }


def measure_case(
    con: duckdb.DuckDBPyConnection,
    pages_dir: str | Path,
    transcribers: dict,
    sample: int = 10,
    intake_dir: str | Path | None = None,
) -> dict:
    """Compare vision backends on a sample of **image-only** pages — an analysis
    tool to choose a local model and set the escalation threshold from data.

    ``transcribers`` maps a label (e.g. ``"qwen2.5vl:7b"``) to a
    :class:`Transcriber`. Samples up to ``sample`` pages whose embedded text is
    thin/absent (the pages a vision tier actually handles; needs ``intake_dir``
    to detect them, else samples the first pages), runs each through every
    backend, and returns per-page fidelity per backend plus, for a range of
    thresholds, the fraction of pages each backend would escalate. **Read-only:
    never writes `page_text`.**
    """
    pages_dir = Path(pages_dir)
    intake_dir = Path(intake_dir) if intake_dir is not None else None
    rows = con.execute(
        "SELECT p.id, p.page_image_path, p.image_id, p.page_number, i.intake_path "
        "FROM pages p JOIN images i ON i.id = p.image_id ORDER BY p.id"
    ).fetchall()

    text_cache: dict[str, list[str] | None] = {}
    sampled: list[tuple] = []  # (page_id, png)
    for page_id, rel, image_id, page_number, intake_path in rows:
        if len(sampled) >= sample:
            break
        if intake_dir is not None:
            embedded = _embedded_text(intake_dir, intake_path, image_id, page_number, text_cache)
            if embedded is not None and len(embedded.strip()) >= MIN_PDF_TEXT_CHARS:
                continue  # born-digital — not a vision-tier page
        png = pages_dir / rel
        if png.exists():
            sampled.append((page_id, png))

    # Per page, transcribe with every backend (sequential — this is a deliberate
    # offline measurement, not the hot path).
    per_page: list[dict] = []
    for page_id, png in sampled:
        entry = {"page_id": page_id, "fidelity": {}, "chars": {}}
        for label, transcriber in transcribers.items():
            try:
                out = transcriber.transcribe(png)
                entry["fidelity"][label] = out["fidelity"]
                entry["chars"][label] = len(out["text"])
            except Exception as exc:
                entry["fidelity"][label] = None
                entry["chars"][label] = f"error: {type(exc).__name__}"
        per_page.append(entry)

    labels = list(transcribers)
    avg_fidelity = {}
    for label in labels:
        vals = [e["fidelity"][label] for e in per_page if e["fidelity"].get(label) is not None]
        avg_fidelity[label] = (sum(vals) / len(vals)) if vals else 0.0
    # Escalation fraction: share of sampled pages a backend reads below each T.
    thresholds = (0.7, 0.8, 0.9, 0.95)
    escalation_fraction: dict[str, dict[float, float]] = {label: {} for label in labels}
    n = len(per_page)
    for label in labels:
        for t in thresholds:
            below = sum(1 for e in per_page
                        if (f := e["fidelity"].get(label)) is not None and f < t)
            escalation_fraction[label][t] = (below / n) if n else 0.0

    return {
        "sampled": n,
        "labels": labels,
        "per_page": per_page,
        "avg_fidelity": avg_fidelity,
        "escalation_fraction": escalation_fraction,
    }
