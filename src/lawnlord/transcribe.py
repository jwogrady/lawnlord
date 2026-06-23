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
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Protocol

import duckdb
import pypdfium2 as pdfium

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
# escalate passes (rev 0 immutable; every pass appends the next rev).
_PAGE_TEXT_INSERT = (
    "INSERT INTO page_text (case_id, page_id, rev, source, text, fidelity, "
    "model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


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

    def __init__(self, model: str = DEFAULT_LOCAL_MODEL, host: str | None = None):
        self.model = model
        self._host = (host or DEFAULT_OLLAMA_HOST).rstrip("/")

    def transcribe(self, png_path: str | Path) -> dict:
        import urllib.request

        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "user", "content": _PROMPT, "images": [_b64_png(png_path)]}
            ],
            "stream": False,
            "format": _OUTPUT_SCHEMA,
            "options": {"temperature": 0},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self._host}/api/chat", data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read())
        data = json.loads(body["message"]["content"])
        return {
            "text": data.get("transcription", ""),
            "fidelity": float(data.get("fidelity", 0.0)),
            "model": self.model,
        }


def ollama_available(model: str = DEFAULT_LOCAL_MODEL, host: str | None = None) -> bool:
    """True if the Ollama server is reachable and ``model`` is pulled — the gate
    the CLI uses to decide local vs the cloud fallback."""
    import urllib.request

    host = (host or DEFAULT_OLLAMA_HOST).rstrip("/")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as resp:
            tags = json.loads(resp.read())
    except Exception:
        return False
    names = {m.get("name", "") for m in tags.get("models", [])}
    if model in names or f"{model}:latest" in names:
        return True
    # A bare name (no explicit ``:tag``) matches any pulled tag of that repo; an
    # explicit tag must match exactly — else we'd green-light a tag that isn't
    # pulled and the call would fail at runtime instead of falling back to cloud.
    if ":" not in model:
        return any(n.split(":", 1)[0] == model for n in names)
    return False


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
            if attempt + 1 >= attempts or not _is_transient(exc):
                raise
            # Exponential backoff with jitter, so concurrent workers don't retry
            # in lockstep against a shared overloaded API.
            delay = base_delay * (2 ** attempt)
            time.sleep(delay * (0.5 + random.random()))


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


def transcribe_case(
    con: duckdb.DuckDBPyConnection,
    pages_dir: str | Path,
    generated_at: str,
    transcriber: Transcriber,
    force: bool = False,
    intake_dir: str | Path | None = None,
    max_workers: int = DEFAULT_WORKERS,
) -> dict:
    """Transcribe pages in the `pages` table, appending to `page_text`.

    Two sources, cheapest first. **Text-layer pre-pass (ADR-0004):** when
    ``intake_dir`` is given, a born-digital page's exact text is read straight
    from its PDF (``source='pdf_text'``, ``fidelity=1.0``, no model call). Only a
    page with no usable embedded text falls through to the **vision tier** —
    ``transcriber`` (cloud or local; ADR-0001/0002) → ``source='ai'`` — which
    needs the rendered PNG under ``pages_dir``.

    The vision calls (network-bound) run concurrently in a bounded pool of
    ``max_workers``, retried with backoff on transient API errors; a page that
    still fails is reported in ``failed`` rather than aborting the run. Every
    DuckDB write stays on the calling thread, and **each page is committed the
    moment it finishes** — so an interrupted run keeps the pages already done and
    a re-run costs only the rest. Output is read back in page/rev order, so the
    completion order of the concurrent writes is not observable (ADR-0003).

    Resumable by default: a page that already has a `page_text` row is **skipped**
    (only-missing). ``force=True`` re-runs every page, appending the next rev
    (rev 0 stays immutable; revisions are never overwritten).
    """
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

    # Phase 1 (sequential, page order): a born-digital page is committed now
    # (its text is local and free); a page needing vision is queued for phase 2.
    vision: list[tuple] = []
    for page_id, case_id, rel, image_id, page_number, intake_path in rows:
        prev = con.execute(
            "SELECT max(rev) FROM page_text WHERE page_id = ?", [page_id]
        ).fetchone()[0]
        if prev is not None and not force:
            skipped_existing.append(page_id)
            continue
        rev = 0 if prev is None else prev + 1

        # Lever 0: a born-digital page already holds its exact text — store it
        # verbatim (fidelity 1.0, no model). Distinct from OCR; see ADR-0004.
        embedded = _embedded_text(intake_dir, intake_path, image_id, page_number, text_cache)
        if embedded is not None and len(embedded.strip()) >= MIN_PDF_TEXT_CHARS:
            con.execute(_PAGE_TEXT_INSERT, [case_id, page_id, rev, "pdf_text", embedded,
                                  1.0, None, generated_at])
            pdf_text += 1
            continue

        # No usable text layer → vision tier (needs the rendered PNG).
        png = pages_dir / rel
        if not png.exists():
            skipped.append(rel)
            continue
        vision.append((page_id, case_id, rev, png))

    # Phase 2 (concurrent): the network-bound vision calls. Each result is
    # committed on this thread as its future completes, so progress is durable
    # mid-run; a page that fails after retries is reported, not dropped.
    if vision:
        workers = max(1, min(max_workers, len(vision)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_page = {
                pool.submit(_transcribe_with_retry, transcriber, png):
                    (page_id, case_id, rev)
                for (page_id, case_id, rev, png) in vision
            }
            for future in as_completed(future_to_page):
                page_id, case_id, rev = future_to_page[future]
                try:
                    result = future.result()
                except Exception:
                    failed.append(page_id)
                    continue
                con.execute(_PAGE_TEXT_INSERT, [case_id, page_id, rev, "ai", result["text"],
                                      result["fidelity"], result["model"], generated_at])
                done += 1
                fidelity_sum += result["fidelity"]

    return {
        "pages": done,
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
    # Latest rev per page; keep only model pages (not pdf_text) below threshold.
    rows = con.execute(
        "SELECT pt.case_id, pt.page_id, pt.rev, p.page_image_path "
        "FROM page_text pt "
        "JOIN pages p ON p.id = pt.page_id "
        "JOIN (SELECT page_id, max(rev) AS mrev FROM page_text GROUP BY page_id) m "
        "  ON m.page_id = pt.page_id AND m.mrev = pt.rev "
        "WHERE pt.source = 'ai' AND pt.fidelity < ? "
        "ORDER BY pt.page_id",
        [threshold],
    ).fetchall()

    targets = []
    failed: list[str] = []
    for case_id, page_id, rev, rel in rows:
        png = pages_dir / rel
        if not png.exists():
            failed.append(page_id)
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
                except Exception:
                    failed.append(page_id)
                    continue
                con.execute(_PAGE_TEXT_INSERT, [case_id, page_id, rev, "ai",
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
    escalation_fraction = {label: {} for label in labels}
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
