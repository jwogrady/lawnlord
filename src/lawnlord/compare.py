"""Emit the page-by-page compare artifact for the web reviewer.

For each page, render the **actual** original page and the **reconstructed** page
(the master rebuilt from the data, :func:`assemble.assemble_from_index`), and
record lawnlord's **score** (the #33 confidence) plus a short note. The output —
``compare.json`` + ``images/`` — is what ``web/`` reads (point its ``COMPARE_DIR``
at it). OCR runs on the GPU when ``ocr`` is built with ``use_gpu=True``.
"""

from __future__ import annotations

import json
from collections import defaultdict
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
    declared_by: dict[str, int | None] = {}
    actual_by: dict[str, int | None] = {}
    rendered: dict[str, set[int]] = defaultdict(set)
    try:
        for pg in amanifest["pageProvenance"]:
            filename, spn, mpage = pg["image"], pg["sourcePage"], pg["masterPage"]
            row = con.execute(
                """
                SELECT i.intake_path, i.title,
                       i.declared_page_count, i.actual_page_count,
                       COALESCE(i.page_count_mismatch, TRUE),
                       e.event_type, e.date,
                       c.confidence, c.text_source,
                       (c.text IS NOT NULL AND length(trim(c.text)) > 0),
                       d.title, d.document_family, c.text
                FROM chunks c
                JOIN images i ON i.id = c.image_id
                LEFT JOIN image_events ie ON ie.image_id = i.id
                LEFT JOIN events e ON e.id = ie.event_id
                LEFT JOIN documents d ON d.id = c.document_id
                WHERE i.filename = ? AND c.source_page_number = ? LIMIT 1
                """,
                [filename, spn],
            ).fetchone()
            (intake_path, img_title, declared, actual, mismatch,
             ev_type, ev_date, conf, tsource, has_text,
             doc_title, doc_family, text) = row or (
                None, filename, None, None, True,
                None, None, None, None, False, None, None, "",
            )
            stem = Path(filename).stem
            actual_name = f"{stem}-p{spn:03d}-actual.png"
            if intake_path:
                src = src_cache.get(filename)
                if src is None:
                    src = fitz.open(case.intake_dir / intake_path)
                    src_cache[filename] = src
                if 1 <= spn <= src.page_count:
                    _render(src[spn - 1], images_dir / actual_name, dpi)
            declared_by[filename] = declared
            actual_by[filename] = actual
            rendered[filename].add(spn)
            pages.append(
                {
                    "id": f"{stem}_p{spn}",
                    # the court's structure: case -> filing (submission event) -> image
                    "filing": {
                        "title": img_title or filename,
                        "type": ev_type or "",
                        "date": ev_date or "",
                    },
                    "image": filename,
                    "declaredPages": declared,
                    "actualPages": actual,
                    "mismatch": bool(mismatch),
                    "page": spn,
                    # ADDITIVE: the boundary-detected sub-unit (analysis, not the
                    # court's structure) — annotation on the page, never the root.
                    "document": (
                        {"title": doc_title, "family": doc_family or ""}
                        if doc_title
                        else None
                    ),
                    # LEFT: the filed page (original). RIGHT: our textual
                    # representation — the text in DuckDB and burned into the
                    # reconstructed PDF. Comparing image-to-text is how a human
                    # verifies the data is faithful to the filing.
                    "actual": f"/images/{actual_name}",
                    "text": text or "",
                    "textSource": tsource or ("none" if not has_text else "pdf"),
                    # the assembled reconstruction (text + any assets), lossless
                    "masterPage": mpage,
                    "score": round(conf if conf is not None else 0.0, 3),
                    "note": _note(bool(mismatch), bool(has_text), tsource),
                }
            )
    finally:
        master.close()
        for src in src_cache.values():
            src.close()
        con.close()

    integrity = _reconcile(rendered, declared_by, actual_by, len(pages))
    (out_dir / "compare.json").write_text(
        json.dumps(
            {
                "case": case.case_number,
                "masterPdf": master_path.name,
                "integrity": integrity,
                "pages": pages,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if integrity["errors"]:
        raise ValueError(
            "compare does not reconcile with the source — pages missing:\n  "
            + "\n  ".join(integrity["errors"])
        )
    return {
        "case": case.case_number,
        "pages": len(pages),
        "out": str(out_dir),
        "flags": len(integrity["flags"]),
    }


def _reconcile(
    rendered: dict[str, set[int]],
    declared_by: dict[str, int | None],
    actual_by: dict[str, int | None],
    total_pages: int,
) -> dict:
    """Compare the rendered output against the court manifest, per image.

    Hard error if we hold a source page we failed to render (a real drop).
    Flag — a finding, not a tool bug — when the docket's declared page count
    disagrees with the actual file. Never silent: both land in compare.json.
    """
    images: list[dict] = []
    errors: list[str] = []
    flags: list[str] = []
    for name in sorted(rendered):
        r = len(rendered[name])
        actual = actual_by.get(name)
        declared = declared_by.get(name)
        images.append(
            {"image": name, "rendered": r, "actual": actual, "declared": declared}
        )
        if actual is not None and r != actual:
            errors.append(f"{name}: rendered {r} of {actual} source pages")
        if declared is not None and actual is not None and declared != actual:
            flags.append(f"{name}: docket declares {declared} pages, file has {actual}")
    return {
        "renderedPages": total_pages,
        "declaredPages": sum(v or 0 for v in declared_by.values()),
        "images": images,
        "ok": not errors,
        "errors": errors,
        "flags": flags,
    }
