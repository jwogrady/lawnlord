"""Explode each filed PDF (image) into its documents and pages, rendering every
page to a PNG — the data prep the Exploded lens and transcription consume.

This is the **additive** layer on top of the immutable mirror: it reads the
mirror's ``images`` and writes ``documents`` + ``pages`` (with a PNG per page),
never touching the mirror. Boundary detection starts simple — one document per
image (the whole filed PDF); finer splitting is a later issue. Page counts are
cross-checked against the docket's declared count and mismatches are surfaced,
never hidden.

Rendering is deterministic: pypdfium2 at a fixed scale → Pillow PNG (no embedded
timestamp), so re-exploding identical input yields identical bytes.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pypdfium2 as pdfium

from .hashing import sha256_file

# 150 DPI: legible page renders without ballooning PNG size. Fixed for determinism.
RENDER_DPI = 150


def explode_case(
    con: duckdb.DuckDBPyConnection,
    intake_dir: str | Path,
    out_dir: str | Path,
    generated_at: str,
    dpi: int = RENDER_DPI,
) -> dict:
    """Render every image's pages to PNGs under ``out_dir`` and populate the
    ``documents`` + ``pages`` tables. Returns counts and page-count mismatches.

    ``intake_dir`` holds the filed PDFs (``files/…``); ``out_dir`` is where the
    page PNGs are written (``out_dir/<image_id>/pNNN.png``). Drop-and-rebuild for
    this case's exploded rows, so re-running identical input is reproducible.
    """
    intake_dir = Path(intake_dir)
    out_dir = Path(out_dir)
    row = con.execute("SELECT id FROM cases LIMIT 1").fetchone()
    if row is None:
        raise ValueError("no case in the mirror — run `lawnlord import` first")
    case_id = row[0]

    con.execute("DELETE FROM pages WHERE case_id = ?", [case_id])
    con.execute("DELETE FROM documents WHERE case_id = ?", [case_id])

    images = con.execute(
        "SELECT id, intake_path, title, declared_page_count FROM images "
        "ORDER BY id"
    ).fetchall()

    scale = dpi / 72.0
    rendered_pages = 0
    skipped: list[str] = []
    mismatches: list[dict] = []

    for image_id, intake_path, title, declared in images:
        pdf_path = intake_dir / intake_path
        if not pdf_path.exists():
            skipped.append(intake_path)
            continue

        # One document per image (the whole filed PDF) — finer splitting later.
        doc_id = f"{image_id}_doc"
        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            page_count = len(pdf)
            con.execute(
                "INSERT INTO documents (id, case_id, image_id, title, page_count, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                [doc_id, case_id, image_id, title, page_count, generated_at],
            )
            image_out = out_dir / image_id
            image_out.mkdir(parents=True, exist_ok=True)
            for i in range(page_count):
                page = pdf[i]
                png_path = image_out / f"p{i + 1:03d}.png"
                page.render(scale=scale).to_pil().save(png_path)
                page.close()
                con.execute(
                    "INSERT INTO pages (id, case_id, image_id, document_id, "
                    "page_number, page_image_path, page_image_sha256, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        f"{doc_id}_p{i + 1:03d}", case_id, image_id, doc_id, i + 1,
                        png_path.relative_to(out_dir).as_posix(),
                        sha256_file(png_path), generated_at,
                    ],
                )
                rendered_pages += 1
        finally:
            pdf.close()

        if declared is not None and declared != page_count:
            mismatches.append(
                {"image_id": image_id, "declared": declared, "rendered": page_count}
            )

    return {
        "documents": len(images) - len(skipped),
        "pages": rendered_pages,
        "skipped_images": skipped,
        "mismatches": mismatches,
    }
