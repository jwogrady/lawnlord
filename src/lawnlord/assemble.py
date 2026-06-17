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

from .workspace import Case


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


def assemble_case(
    case: Case, output_path: str | Path, *, verify: bool = True
) -> dict:
    """Reassemble the case's images into one master PDF at ``output_path``.

    Builds a Filing -> Image -> Document outline, carries embedded attachments,
    writes a ``<output>.manifest.json`` page-provenance sidecar, and (when
    ``verify``) checks that every master page's text matches its source page.
    Returns an integrity report.
    """
    output_path = Path(output_path)
    master = fitz.open()
    toc: list[list] = []
    pages: list[dict] = []
    src_text: list[str] = []
    missing: list[str] = []
    embedded_total = 0
    prev_filing: tuple[str, str] | None = None

    for image_path in _ordered_images(case):
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
            pages.append(
                {
                    "masterPage": start + i + 1,
                    "image": name,
                    "sourcePage": i + 1,
                    "filingEvent": event,
                    "filingDate": date,
                }
            )
        embedded_total += _carry_embedded_files(master, src, name)
        master.insert_pdf(src)
        src.close()

    master.set_toc(toc)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    master.save(output_path, garbage=4, deflate=True)

    text_lossless: bool | None = None
    if verify:
        text_lossless = all(
            hashlib.sha256(master[i].get_text().encode()).hexdigest()
            == hashlib.sha256(src_text[i].encode()).hexdigest()
            for i in range(master.page_count)
        )
    master_pages = master.page_count
    master.close()

    manifest = {
        "case": case.case_number,
        "masterPdf": str(output_path),
        "images": len({p["image"] for p in pages}),
        "pages": master_pages,
        "outline": [{"level": lvl, "title": t, "masterPage": pg} for lvl, t, pg in toc],
        "pageProvenance": pages,
        "embeddedAttachmentsCarried": embedded_total,
        "missingImages": missing,
        "textLossless": text_lossless,
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
        "embedded_attachments": embedded_total,
        "missing": missing,
        "text_lossless": text_lossless,
    }
