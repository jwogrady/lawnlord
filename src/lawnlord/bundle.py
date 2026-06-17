"""The capstone: wrap a complete case into one self-contained bundle.

``lawnlord bundle`` produces the final output — the complete exploded case
content wrapped inside the standard contextual metadata, fully cross-linked:

    <case>.bundle.zip
      case.json            standard metadata wrapper (court schema down to image)
      filings/<pdf>        preserved original PDFs (immutable, hash-pinned) — case.json's doc.file points here
      case-master.pdf      the whole case reassembled in docket order (lossless)
      pages/<stem>/pNNN.txt per-page extracted text (fully searchable)
      lawnlord.duckdb      the queryable index (regenerable)
      bundle-manifest.json cross-links: image <-> its pages <-> master-PDF pages <-> filing

The metadata is the outer wrapper and index; the content lives inside it; every
record links both ways. Reading only ``case.json`` reaches every image (via its
``file`` path), and the bundle-manifest ties each image to its pages, its
master-PDF page range, and its filing. Self-contained (every entry is a relative
path inside the zip) and regenerable from the intake.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from .assemble import assemble_case
from .boundaries import load_manual_boundaries
from .canonical import to_canonical
from .corpus import write_corpus
from .curation import load_curation
from .db import apply_schema, open_case_db
from .index import index_corpus
from .ingest import ingest_case
from .ocr import make_lazy_ocr
from .unify import unify
from .workspace import Case

CASE_JSON_NAME = "case.json"
MASTER_PDF_NAME = "case-master.pdf"
DUCKDB_NAME = "lawnlord.duckdb"
BUNDLE_MANIFEST_NAME = "bundle-manifest.json"


def _build_index(case: Case, ocr) -> str:
    """Explode + ingest + index the case into its (work) case_dir. Returns the
    corpus ``generatedAt``."""
    manifest = write_corpus(
        case.filings_dir,
        case.corpus_dir,
        force=False,
        manual_boundaries=load_manual_boundaries(case.intake_dir / "bundle-boundaries.json"),
        curation=load_curation(case.intake_dir / "corpus-curation.json"),
        ocr=ocr,
    )
    generated_at = manifest["generatedAt"]
    con = open_case_db(case.duckdb_path)
    apply_schema(con)
    ingest_case(con, case, generated_at)
    index_corpus(con, case, case.corpus_dir, generated_at)
    con.close()
    return generated_at


def _page_text(case: Case) -> list[dict]:
    """Per-page text from the index, with its image and source page."""
    con = open_case_db(case.duckdb_path, read_only=True)
    try:
        rows = con.execute(
            """
            SELECT i.filename, c.source_page_number, c.text
            FROM chunks c JOIN images i ON i.id = c.image_id
            ORDER BY i.filename, c.source_page_number
            """
        ).fetchall()
    finally:
        con.close()
    return [{"filename": f, "sourcePage": p, "text": t or ""} for f, p, t in rows]


def _image_hashes(case: Case) -> dict[str, str]:
    con = open_case_db(case.duckdb_path, read_only=True)
    try:
        rows = con.execute("SELECT filename, sha256_hash FROM images").fetchall()
    finally:
        con.close()
    return {f: h for f, h in rows}


def _cross_links(assemble_stats_manifest: dict, hashes: dict[str, str]) -> list[dict]:
    """Group the assemble page-provenance by image into the cross-link records:
    image <-> master-PDF page range <-> its pages <-> filing."""
    by_image: dict[str, dict] = {}
    for pg in assemble_stats_manifest["pageProvenance"]:
        name = pg["image"]
        rec = by_image.setdefault(
            name,
            {
                "filename": name,
                "sha256": hashes.get(name, ""),
                "file": f"filings/{name}",
                "filing": {"event": pg["filingEvent"], "date": pg["filingDate"]},
                "masterPageStart": pg["masterPage"],
                "masterPageEnd": pg["masterPage"],
                "pages": [],
            },
        )
        rec["masterPageEnd"] = max(rec["masterPageEnd"], pg["masterPage"])
        rec["masterPageStart"] = min(rec["masterPageStart"], pg["masterPage"])
        stem = Path(name).stem
        rec["pages"].append(
            {
                "sourcePage": pg["sourcePage"],
                "masterPage": pg["masterPage"],
                "text": f"pages/{stem}/p{pg['sourcePage']:03d}.txt",
            }
        )
    return list(by_image.values())


def bundle_case(case: Case, out_zip: str | Path, *, ocr=None) -> dict:
    """Build the self-contained case bundle at ``out_zip``. Returns stats."""
    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    ocr = ocr if ocr is not None else make_lazy_ocr()

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        wcase = Case.from_intake(case.intake_dir, case_dir=work)
        _build_index(wcase, ocr)

        master_path = work / MASTER_PDF_NAME
        astats = assemble_case(wcase, master_path)
        amanifest = json.loads(Path(astats["manifest"]).read_text(encoding="utf-8"))

        canonical = to_canonical(unify(wcase.model))
        hashes = _image_hashes(wcase)
        pages = _page_text(wcase)
        cross = _cross_links(amanifest, hashes)

        bundle_manifest = {
            "case": wcase.case_number,
            "schemaVersion": canonical["schemaVersion"],
            "caseJson": CASE_JSON_NAME,
            "masterPdf": MASTER_PDF_NAME,
            "duckdb": DUCKDB_NAME,
            "lossless": {
                "text": amanifest.get("textLossless"),
                "visual": amanifest.get("visualLossless"),
            },
            "images": cross,
        }

        packed_images = 0
        missing: list[str] = []
        seen: set[str] = set()
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(CASE_JSON_NAME, json.dumps(canonical, indent=2))
            z.writestr(BUNDLE_MANIFEST_NAME, json.dumps(bundle_manifest, indent=2))
            z.write(master_path, MASTER_PDF_NAME)
            z.write(wcase.duckdb_path, DUCKDB_NAME)
            # Preserved originals at the path case.json references (filings/<name>).
            for doc in wcase.model.documents:
                rel = doc.intake_path
                if not rel or rel in seen:
                    continue
                seen.add(rel)
                src = wcase.intake_dir / rel
                if not src.exists():
                    missing.append(rel)
                    continue
                z.write(src, rel)
                packed_images += 1
            # Per-page searchable text.
            for pg in pages:
                stem = Path(pg["filename"]).stem
                z.writestr(f"pages/{stem}/p{pg['sourcePage']:03d}.txt", pg["text"])

        return {
            "case": wcase.case_number,
            "out_zip": str(out_zip),
            "images": packed_images,
            "pages": len(pages),
            "master_pages": astats["pages"],
            "text_lossless": astats["text_lossless"],
            "visual_lossless": astats["visual_lossless"],
            "missing": missing,
        }
