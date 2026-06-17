"""Emit the page-by-page compare artifact for the web reviewer.

For each page, render the **actual** original page and the **reconstructed** page
(the master rebuilt from the data, :func:`assemble.assemble_from_index`), and
record lawnlord's **score** (the #33 confidence) plus a short note. The output —
``compare.json`` + ``images/`` — is what ``web/`` reads (point its ``COMPARE_DIR``
at it). OCR runs on the GPU when ``ocr`` is built with ``use_gpu=True``.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from .assemble import assemble_from_index
from .boundaries import load_manual_boundaries
from .corpus import write_corpus
from .curation import load_curation
from .db import apply_schema, open_case_db
from .index import index_corpus
from .ingest import ingest_case
from .ocr import make_lazy_ocr
from .workspace import Case

RENDER_DPI = 150


def _render(page: fitz.Page, path: Path, dpi: int) -> None:
    page.get_pixmap(dpi=dpi).save(path)


def _note(mismatch: bool, has_text: bool, text_source: str | None) -> str:
    if mismatch:
        return "Declared vs actual page count mismatch — flagged for review."
    if not has_text:
        return "No text on this page — not searchable; verify the image."
    if text_source == "ocr":
        return "Text recovered via OCR — verify against the image."
    return "Native text layer; declared page count matches. High confidence."


def emit_compare(
    case: Case, out_dir: str | Path, *, ocr=None, dpi: int = RENDER_DPI, build: bool = True
) -> dict:
    """Build (optionally) and render the compare artifact at ``out_dir``.

    When ``build`` is true, explode + ingest + index the case first (running OCR
    via ``ocr``). Then reconstruct the master from the data and render, per page,
    the actual original page and the reconstructed page, writing ``compare.json``.
    Returns a summary.
    """
    out_dir = Path(out_dir)
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    ocr = ocr if ocr is not None else make_lazy_ocr()

    if build:
        manifest = write_corpus(
            case.filings_dir,
            case.corpus_dir,
            force=False,
            manual_boundaries=load_manual_boundaries(case.intake_dir / "bundle-boundaries.json"),
            curation=load_curation(case.intake_dir / "corpus-curation.json"),
            ocr=ocr,
        )
        con = open_case_db(case.duckdb_path)
        apply_schema(con)
        ingest_case(con, case, manifest["generatedAt"])
        index_corpus(con, case, case.corpus_dir, manifest["generatedAt"])
        con.close()

    master_path = out_dir / "case-master.pdf"
    astats = assemble_from_index(case, master_path)
    amanifest = json.loads(Path(astats["manifest"]).read_text(encoding="utf-8"))

    con = open_case_db(case.duckdb_path, read_only=True)
    master = fitz.open(master_path)
    src_cache: dict[str, fitz.Document] = {}
    pages: list[dict] = []
    try:
        for pg in amanifest["pageProvenance"]:
            filename, spn, mpage = pg["image"], pg["sourcePage"], pg["masterPage"]
            row = con.execute(
                """
                SELECT i.intake_path, COALESCE(i.page_count_mismatch, TRUE),
                       c.confidence, c.text_source,
                       (c.text IS NOT NULL AND length(trim(c.text)) > 0)
                FROM chunks c JOIN images i ON i.id = c.image_id
                WHERE i.filename = ? AND c.source_page_number = ? LIMIT 1
                """,
                [filename, spn],
            ).fetchone()
            intake_path, mismatch, conf, tsource, has_text = row or (
                None, True, None, None, False,
            )
            stem = Path(filename).stem
            actual_name = f"{stem}-p{spn:03d}-actual.png"
            recon_name = f"{stem}-p{spn:03d}-recon.png"
            if intake_path:
                src = src_cache.get(filename)
                if src is None:
                    src = fitz.open(case.intake_dir / intake_path)
                    src_cache[filename] = src
                if 1 <= spn <= src.page_count:
                    _render(src[spn - 1], images_dir / actual_name, dpi)
            _render(master[mpage - 1], images_dir / recon_name, dpi)
            pages.append(
                {
                    "id": f"{stem}_p{spn}",
                    "image": filename,
                    "page": spn,
                    "actual": f"/images/{actual_name}",
                    "reconstructed": f"/images/{recon_name}",
                    "score": round(conf if conf is not None else 0.0, 3),
                    "note": _note(bool(mismatch), bool(has_text), tsource),
                }
            )
    finally:
        master.close()
        for src in src_cache.values():
            src.close()
        con.close()

    (out_dir / "compare.json").write_text(
        json.dumps({"case": case.case_number, "pages": pages}, indent=2), encoding="utf-8"
    )
    return {"case": case.case_number, "pages": len(pages), "out": str(out_dir)}
