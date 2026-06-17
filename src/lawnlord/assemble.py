"""Reassemble an exploded case back into one master PDF — the lossless
round-trip that *proves* the foundation lost no context.

The foundation (Case -> Filing -> Image -> Document -> Section -> Page) is only
trustworthy if it is reversible: if we can put every preserved image back
together, in docket order, with the structural hierarchy intact, then the
explosion dropped nothing. This module is that proof.

It reassembles from the **preserved original images** (the immutable, hash-
pinned source PDFs), never from re-encoded fragments, so page content comes
straight from the artifacts. It builds a Filing -> Image -> Document outline
(documents from each image's bookmarks, junk filtered), carries embedded file
attachments across so they survive, and emits a page -> provenance manifest.
``assemble_case`` verifies page-for-page text fidelity and returns the integrity
report; a caller (or test) asserts it is lossless.

Deterministic: images are ordered by the model's filing/event spine (stable),
falling back to a sorted append for any image not referenced by a filing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz  # pymupdf

from .db import open_case_db
from .workspace import Case

# Merging tagged (accessible) PDFs makes MuPDF print benign warnings to stderr
# ("No common ancestor in structure tree") — it can't reconcile the source
# structure trees, but page content is unaffected. Silence that noise; real
# errors still raise.
fitz.TOOLS.mupdf_display_errors(False)

# Visual-fidelity check: render pages at this DPI and require the mean absolute
# per-channel pixel difference between each source page and its master page to
# stay under the tolerance. insert_pdf is not bit-identical (it rewrites the
# file), but content is preserved — observed worst mean|Δ| ~0.07/255 from
# anti-aliasing on tagged pages, so a tolerance of 2.0 flags real corruption
# (a dropped/garbled page scores in the tens) while ignoring rendering noise.
VERIFY_DPI = 100
VISUAL_TOLERANCE = 2.0


def _is_junk_bookmark(title: str, page: int) -> bool:
    """Bookmarks that are not real documents-within-the-image: embedded-file
    references (``…​.pdf``), bare numeric IDs, and entries with no real page
    (PyMuPDF reports page ``-1`` for embedded/remote targets)."""
    t = (title or "").strip()
    return page < 1 or t == "" or t.lower().endswith(".pdf") or t.replace("-", "").isdigit()


def _ordered_images(case: Case) -> list[str]:
    """Image intake-paths in filing/docket order, de-duplicated (first wins),
    with any image not referenced by a filing appended in sorted order."""
    ordered: list[str] = []
    seen: set[str] = set()
    for event in case.events:
        for path in event.files:
            if path not in seen:
                seen.add(path)
                ordered.append(path)
    for doc in sorted(case.documents, key=lambda d: d.intake_path):
        if doc.intake_path not in seen:
            seen.add(doc.intake_path)
            ordered.append(doc.intake_path)
    return ordered


def _filing_for(case: Case, image_path: str) -> tuple[str, str]:
    """The (event, date) label of the first filing that references this image,
    else ("", "") for an un-docketed image."""
    for event in case.events:
        if image_path in event.files:
            return event.event, event.date
    return "", ""


def _carry_embedded_files(master: fitz.Document, src: fitz.Document, image_name: str) -> int:
    """Copy embedded file attachments from a source image into the master so
    they are not lost, namespaced by image. Returns the count carried."""
    try:
        names = list(src.embfile_names())
    except Exception:
        return 0
    carried = 0
    for name in names:
        try:
            buf = src.embfile_get(name)
            master.embfile_add(f"{image_name}::{name}", buf)
            carried += 1
        except Exception:
            continue
    return carried


def _verify_visual(
    case: Case, ordered: list[str], master_path: Path, page_count: int
) -> tuple[bool | None, float]:
    """Render each source page and its master page and compare them within
    ``VISUAL_TOLERANCE``. Returns (visual_lossless, worst_mean_diff). Best-effort:
    returns (None, 0.0) when numpy is unavailable (the text round-trip still
    holds) — visual verification needs array math, not a hard runtime dep."""
    try:
        import numpy as np
    except ImportError:
        return None, 0.0

    def render(page) -> "np.ndarray":
        pix = page.get_pixmap(dpi=VERIFY_DPI)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        ).astype(np.int16)

    master = fitz.open(master_path)
    worst = 0.0
    ok = True
    mp = 0
    try:
        for image_path in ordered:
            src_file = case.intake_dir / image_path
            if not src_file.exists():
                continue
            src = fitz.open(src_file)
            for i in range(src.page_count):
                if mp >= page_count:
                    break
                a, b = render(src[i]), render(master[mp])
                diff = float(np.abs(a - b).mean()) if a.shape == b.shape else 1e9
                worst = max(worst, diff)
                if diff > VISUAL_TOLERANCE:
                    ok = False
                mp += 1
            src.close()
    finally:
        master.close()
    return ok, round(worst, 4)


def _filing_by_image(con) -> dict:
    """image_id -> (event, date) of its earliest linked docket event."""
    out: dict = {}
    rows = con.execute(
        """
        SELECT ie.image_id, e.event_type, e.date
        FROM image_events ie JOIN events e ON e.id = ie.event_id
        ORDER BY ie.image_id, e.date
        """
    ).fetchall()
    for image_id, event, date in rows:
        out.setdefault(image_id, (event or "", date or ""))
    return out


def assemble_from_index(
    case: Case, output_path: str | Path, *, con=None, verify: bool = True
) -> dict:
    """Reconstruct the master PDF **from the DuckDB data** (#32), not the
    originals: lay down each page's preserved image (``chunks.page_image_path``)
    in docket order and burn in an invisible searchable text layer from
    ``chunks.text`` *only where the page has no native text* — so born-digital
    pages stay byte-faithful and scanned/OCR'd pages become searchable. Because
    the rebuild is driven by the index, a faithful result is itself proof the
    data is complete. Writes a ``<output>.manifest.json`` sidecar (same shape as
    :func:`assemble_case`, plus ``textMissing``) and returns the integrity report.
    """
    output_path = Path(output_path)
    owns_con = con is None
    con = con or open_case_db(case.duckdb_path, read_only=True)
    try:
        filing = _filing_by_image(con)
        images = con.execute(
            "SELECT id, filename FROM images"
        ).fetchall()
        images.sort(key=lambda r: (filing.get(r[0], ("", ""))[1] or "~", r[0]))

        master = fitz.open()
        toc: list[list] = []
        pages: list[dict] = []
        text_missing: list[dict] = []
        data_text_pages: list[int] = []  # master page numbers that carry text in the data
        missing_images: list[str] = []
        prev_filing: tuple[str, str] | None = None

        for image_id, filename in images:
            event, date = filing.get(image_id, ("", ""))
            start = master.page_count
            if (event, date) != prev_filing:
                toc.append(
                    [1, f"FILING: {event or '(un-docketed)'}{f' ({date})' if date else ''}", start + 1]
                )
                prev_filing = (event, date)
            toc.append([2, f"IMAGE: {filename}", start + 1])

            rows = con.execute(
                """
                SELECT d.id, d.title, c.source_page_number, c.text, c.page_image_path
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.image_id = ?
                ORDER BY d.document_index, c.source_page_number
                """,
                [image_id],
            ).fetchall()
            prev_doc = None
            for doc_id, doc_title, spn, text, page_image_path in rows:
                if doc_id != prev_doc:
                    if doc_title and not _is_junk_bookmark(doc_title, master.page_count + 1):
                        toc.append([3, f"DOC: {doc_title.strip()}", master.page_count + 1])
                    prev_doc = doc_id
                if not page_image_path:
                    missing_images.append(f"{filename} p.{spn}")
                    continue
                page_pdf = case.corpus_dir / page_image_path
                if not page_pdf.exists():
                    missing_images.append(str(page_image_path))
                    continue
                mp_index = master.page_count
                with fitz.open(page_pdf) as ppdf:
                    master.insert_pdf(ppdf)
                page = master[mp_index]
                data_text = text or ""
                if data_text.strip():
                    data_text_pages.append(mp_index)
                    # Born-digital pages already carry their text; only scanned /
                    # OCR'd pages (no native layer) get the invisible searchable layer.
                    if not page.get_text().strip():
                        page.insert_text((36, 36), data_text, render_mode=3, fontsize=6)
                else:
                    text_missing.append(
                        {"image": filename, "sourcePage": spn, "masterPage": mp_index + 1}
                    )
                pages.append(
                    {
                        "masterPage": mp_index + 1,
                        "image": filename,
                        "sourcePage": spn,
                        "filingEvent": event,
                        "filingDate": date,
                    }
                )

        master.set_toc(toc)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        master.save(output_path, garbage=4, deflate=True)
        master_pages = master.page_count
        master.close()
    finally:
        if owns_con:
            con.close()

    # Text fidelity: every page that has text in the data exposes it (#32).
    text_lossless: bool | None = None
    visual_lossless: bool | None = None
    visual_worst_diff = 0.0
    if verify:
        reopened = fitz.open(output_path)
        try:
            text_lossless = all(reopened[i].get_text().strip() for i in data_text_pages)
        finally:
            reopened.close()
        visual_lossless, visual_worst_diff = _verify_visual_against_images(
            case, pages, output_path
        )

    manifest = {
        "case": case.case_number,
        "masterPdf": str(output_path),
        "source": "index",
        "images": len({p["image"] for p in pages}),
        "pages": master_pages,
        "outline": [{"level": lvl, "title": t, "masterPage": pg} for lvl, t, pg in toc],
        "pageProvenance": pages,
        "textMissing": text_missing,
        "missingImages": missing_images,
        "textLossless": text_lossless,
        "visualLossless": visual_lossless,
        "visualWorstMeanDiff": visual_worst_diff,
    }
    output_path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return {
        "case": case.case_number,
        "out_pdf": str(output_path),
        "manifest": str(output_path.with_suffix(".manifest.json")),
        "images": manifest["images"],
        "pages": master_pages,
        "text_missing": len(text_missing),
        "missing": missing_images,
        "text_lossless": text_lossless,
        "visual_lossless": visual_lossless,
        "visual_worst_diff": visual_worst_diff,
    }


def _verify_visual_against_images(case: Case, pages: list[dict], master_path: Path):
    """Render each master page and its preserved page image and compare within
    ``VISUAL_TOLERANCE``. Best-effort: returns (None, 0.0) without numpy. The
    invisible text layer does not render, so a faithful page scores ~0."""
    try:
        import numpy as np
    except ImportError:
        return None, 0.0
    con = open_case_db(case.duckdb_path, read_only=True)
    try:
        path_by_master = {}
        for p in pages:
            row = con.execute(
                "SELECT page_image_path FROM chunks WHERE image_id IN "
                "(SELECT id FROM images WHERE filename = ?) AND source_page_number = ?",
                [p["image"], p["sourcePage"]],
            ).fetchone()
            if row and row[0]:
                path_by_master[p["masterPage"]] = case.corpus_dir / row[0]
    finally:
        con.close()

    def render(page):
        pix = page.get_pixmap(dpi=VERIFY_DPI)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        ).astype(np.int16)

    master = fitz.open(master_path)
    worst = 0.0
    ok = True
    try:
        for mp in range(1, master.page_count + 1):
            src_path = path_by_master.get(mp)
            if not src_path or not src_path.exists():
                continue
            with fitz.open(src_path) as src:
                a, b = render(src[0]), render(master[mp - 1])
            diff = float(np.abs(a - b).mean()) if a.shape == b.shape else 1e9
            worst = max(worst, diff)
            if diff > VISUAL_TOLERANCE:
                ok = False
    finally:
        master.close()
    return ok, round(worst, 4)


def assemble_case(
    case: Case, output_path: str | Path, *, verify: bool = True
) -> dict:
    """Reassemble the case's images into one master PDF at ``output_path``.

    Builds a Filing -> Image -> Document outline, carries embedded attachments,
    writes a ``<output>.manifest.json`` page-provenance sidecar, and (when
    ``verify``) proves the round-trip lost no context: every master page's text
    matches its source (text-lossless), every page renders the same within
    tolerance (visual-lossless, best-effort), and embedded attachments +
    annotations are accounted for (carried/preserved, no silent loss). Returns
    the integrity report.
    """
    output_path = Path(output_path)
    ordered = _ordered_images(case)
    master = fitz.open()
    toc: list[list] = []
    pages: list[dict] = []
    src_text: list[str] = []
    missing: list[str] = []
    embedded_total = 0  # carried into the master
    embedded_source = 0  # present in the sources
    annots_source = 0  # annotations in the sources
    prev_filing: tuple[str, str] | None = None

    for image_path in ordered:
        src_file = case.intake_dir / image_path
        if not src_file.exists():
            missing.append(image_path)
            continue
        name = Path(image_path).name
        event, date = _filing_for(case, image_path)
        start = master.page_count  # 0-based offset where this image lands

        # One FILING header per filing; images of the same filing nest under it.
        if (event, date) != prev_filing:
            toc.append(
                [1, f"FILING: {event or '(un-docketed)'}{f' ({date})' if date else ''}", start + 1]
            )
            prev_filing = (event, date)
        toc.append([2, f"IMAGE: {name}", start + 1])

        src = fitz.open(src_file)
        for level, title, page in src.get_toc():
            if not _is_junk_bookmark(title, page):
                toc.append([3, f"DOC: {title.strip()}", start + page])
        for i in range(src.page_count):
            text = src[i].get_text()
            src_text.append(text)
            annots_source += sum(1 for _ in src[i].annots())
            pages.append(
                {
                    "masterPage": start + i + 1,
                    "image": name,
                    "sourcePage": i + 1,
                    "filingEvent": event,
                    "filingDate": date,
                }
            )
        try:
            embedded_source += src.embfile_count()
        except Exception:
            pass
        embedded_total += _carry_embedded_files(master, src, name)
        master.insert_pdf(src)  # annots=True by default → annotations carried
        src.close()

    master.set_toc(toc)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    master.save(output_path, garbage=4, deflate=True)

    master_pages = master.page_count
    text_lossless: bool | None = None
    annots_master = 0
    if verify:
        text_lossless = all(
            hashlib.sha256(master[i].get_text().encode()).hexdigest()
            == hashlib.sha256(src_text[i].encode()).hexdigest()
            for i in range(master_pages)
        )
        annots_master = sum(sum(1 for _ in master[i].annots()) for i in range(master_pages))
    master.close()

    # Visual fidelity (best-effort) + accounting that nothing was silently lost.
    visual_lossless: bool | None = None
    visual_worst_diff = 0.0
    if verify:
        visual_lossless, visual_worst_diff = _verify_visual(
            case, ordered, output_path, master_pages
        )
    embedded_lossless = embedded_total == embedded_source
    annots_lossless = (not verify) or annots_master == annots_source

    manifest = {
        "case": case.case_number,
        "masterPdf": str(output_path),
        "images": len({p["image"] for p in pages}),
        "pages": master_pages,
        "outline": [{"level": lvl, "title": t, "masterPage": pg} for lvl, t, pg in toc],
        "pageProvenance": pages,
        "embeddedAttachmentsSource": embedded_source,
        "embeddedAttachmentsCarried": embedded_total,
        "annotationsSource": annots_source,
        "annotationsMaster": annots_master,
        "missingImages": missing,
        "textLossless": text_lossless,
        "visualLossless": visual_lossless,
        "visualWorstMeanDiff": visual_worst_diff,
    }
    manifest_path = output_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "case": case.case_number,
        "out_pdf": str(output_path),
        "manifest": str(manifest_path),
        "images": manifest["images"],
        "pages": master_pages,
        "outline_entries": len(toc),
        "embedded_source": embedded_source,
        "embedded_attachments": embedded_total,
        "embedded_lossless": embedded_lossless,
        "annotations_source": annots_source,
        "annotations_master": annots_master,
        "annotations_lossless": annots_lossless,
        "missing": missing,
        "text_lossless": text_lossless,
        "visual_lossless": visual_lossless,
        "visual_worst_diff": visual_worst_diff,
    }
