"""Spatial-anchor layer: bounding boxes per text span (ADR-0009).

On-image highlighting (#129) needs to know *where on the page* a span sits, but
transcription is text-only. This module captures an **additive, optional**
spatial layer — one bounding box per whitespace token of a born-digital page's
text — anchored to a source row's stable ``id`` via ``(anchor_kind, anchor_id)``.
Today the anchor is a ``page_text`` variation (the ``pdf_text`` reading); later
an analysis entity reuses the same primitive without a schema change.

Geometry comes from the PDF's own glyph boxes via pypdfium2 — precise, free, and
deterministic. Coordinates are stored **normalized 0..1 with a top-left origin**
so they overlay the rendered page PNG at any DPI. A page with no usable text
layer, or whose stored text no longer matches the PDF, is simply skipped — a
region is **never fabricated** (ADR-0009). Vision-model-returned boxes are a
separate, later slice (#128b); no ``origin='model'`` row is written here.

The token unit matches the export layer's divergence spans (``str.split()``), so
a divergence span (a token-index range) maps onto these per-token regions with no
re-derivation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import pypdfium2 as pdfium


def token_char_offsets(text: str) -> list[tuple[int, int]]:
    """The ``(char_start, char_end)`` of each whitespace-delimited token, in
    order. Mirrors ``str.split()`` exactly (runs of whitespace are separators; no
    empty tokens), but keeps each token's character span so it can be mapped to
    glyph boxes. ``token_char_offsets(t)`` has the same length and order as
    ``t.split()``."""
    offsets: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        start = i
        while i < n and not text[i].isspace():
            i += 1
        offsets.append((start, i))
    return offsets


def normalize_rect(
    left: float, bottom: float, right: float, top: float, width: float, height: float
) -> tuple[float, float, float, float]:
    """Convert a pypdfium2 glyph box — PDF points, **bottom-left** origin — to
    ``(x0, y0, x1, y1)`` normalized to ``[0, 1]`` with a **top-left** origin (the
    coordinate space the rendered PNG and the browser overlay share). The y axis
    flips, so the box's ``top`` becomes the smaller ``y0``."""
    return (left / width, (height - top) / height, right / width, (height - bottom) / height)


def span_bbox_points(
    charboxes: list[tuple[float, float, float, float]], char_start: int, char_end: int
) -> tuple[float, float, float, float] | None:
    """Union of the glyph boxes over ``[char_start, char_end)`` in PDF points
    ``(left, bottom, right, top)``, or ``None`` if the range is empty. A token is
    a single contiguous run, so this is its tight bounding box."""
    sub = charboxes[char_start:char_end]
    if not sub:
        return None
    return (
        min(c[0] for c in sub),
        min(c[1] for c in sub),
        max(c[2] for c in sub),
        max(c[3] for c in sub),
    )


def _region_id(anchor_kind: str, anchor_id: str, span_index: int) -> str:
    """Stable surrogate id for one region: a content hash of the **structure**
    ``(anchor_kind, anchor_id, span_index)`` — never the coordinates (which may be
    model-supplied and non-deterministic; ADR-0009). Re-running capture yields
    identical ids, so a re-insert is an idempotent conflict, not a duplicate."""
    digest = hashlib.sha256(f"{anchor_kind}|{anchor_id}|{span_index}".encode()).hexdigest()
    return "pr_" + digest[:16]


def extract_pdf_charboxes(pdf_path: str | Path) -> list[dict]:
    """Per page of ``pdf_path``: ``{"size": (W, H), "text": str, "charboxes":
    [(l, b, r, t), ...]}`` read via pypdfium2 — points, bottom-left origin. The
    charbox list aligns 1:1 with ``text`` (index = character offset). A page with
    no text layer yields an empty string and no boxes."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        out: list[dict] = []
        for i in range(len(pdf)):
            page = pdf[i]
            width, height = page.get_size()
            textpage = page.get_textpage()
            try:
                text = textpage.get_text_range()
                count = textpage.count_chars()
                charboxes = [textpage.get_charbox(k) for k in range(count)]
            finally:
                textpage.close()
                page.close()
            out.append({"size": (width, height), "text": text, "charboxes": charboxes})
        return out
    finally:
        pdf.close()


def capture_pdf_regions(
    con: duckdb.DuckDBPyConnection,
    intake_dir: str | Path,
    generated_at: str,
) -> dict:
    """Capture one ``page_regions`` row per whitespace token of every
    ``pdf_text`` page, from the PDF's glyph geometry. Read-rebuild for the
    ``pdf_text`` origin only (idempotent; any ``model`` rows are untouched).

    For each current ``pdf_text`` variation, the source PDF is read and its
    freshly-extracted text is compared to the stored anchor text; **only when they
    match** are the anchor's tokens mapped to glyph boxes (so character offsets
    always index the right glyphs — a mismatch is skipped, never misaligned). Each
    token becomes a normalized box anchored to the ``page_text`` row's id.

    Deterministic and additive: pages in id order, tokens in order; the mirror and
    the existing transcription layers are never touched.
    """
    intake_dir = Path(intake_dir)
    con.execute("DELETE FROM page_regions WHERE origin = 'pdf_text'")

    # The current pdf_text reading per page (latest rev), with its source PDF.
    rows = con.execute(
        "SELECT pt.id AS anchor_id, pt.text, pt.page_id, pt.case_id, "
        "       p.image_id, p.page_number, i.intake_path "
        "FROM page_text pt "
        "JOIN (SELECT page_id, max(rev) AS rev FROM page_text "
        "      WHERE source = 'pdf_text' GROUP BY page_id) m "
        "  ON m.page_id = pt.page_id AND m.rev = pt.rev "
        "JOIN pages p ON p.id = pt.page_id "
        "JOIN images i ON i.id = p.image_id "
        "WHERE pt.source = 'pdf_text' "
        "ORDER BY pt.page_id"
    ).fetchall()

    regions = 0
    pages_with_geometry = 0
    skipped_no_pdf: list[str] = []
    skipped_mismatch: list[str] = []
    cache: dict[str, list[dict] | None] = {}

    for anchor_id, text, page_id, case_id, image_id, page_number, intake_path in rows:
        if image_id not in cache:
            pdf_path = intake_dir / intake_path if intake_path else None
            try:
                cache[image_id] = (
                    extract_pdf_charboxes(pdf_path)
                    if pdf_path is not None and pdf_path.exists()
                    else None
                )
            except Exception:
                cache[image_id] = None
        pages = cache[image_id]
        idx = page_number - 1
        if pages is None or not (0 <= idx < len(pages)):
            skipped_no_pdf.append(page_id)
            continue
        page = pages[idx]
        charboxes = page["charboxes"]
        # The stored anchor text and the freshly-read text must agree, and the
        # box list must align with it 1:1 — else we cannot trust char offsets.
        if page["text"] != text or len(charboxes) != len(text or ""):
            skipped_mismatch.append(page_id)
            continue
        width, height = page["size"]
        if not (width > 0 and height > 0):
            skipped_mismatch.append(page_id)
            continue
        emitted = False
        for span_index, (char_start, char_end) in enumerate(token_char_offsets(text)):
            box = span_bbox_points(charboxes, char_start, char_end)
            if box is None:
                continue
            x0, y0, x1, y1 = normalize_rect(*box, width, height)
            con.execute(
                "INSERT INTO page_regions (id, case_id, page_id, anchor_id, "
                "anchor_kind, span_index, char_start, char_end, x0, y0, x1, y1, "
                "origin, confidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    _region_id("page_text", anchor_id, span_index),
                    case_id, page_id, anchor_id, "page_text", span_index,
                    char_start, char_end, x0, y0, x1, y1, "pdf_text", 1.0, generated_at,
                ],
            )
            regions += 1
            emitted = True
        if emitted:
            pages_with_geometry += 1

    return {
        "regions": regions,
        "pages_with_geometry": pages_with_geometry,
        "skipped_no_pdf": skipped_no_pdf,
        "skipped_mismatch": skipped_mismatch,
    }
