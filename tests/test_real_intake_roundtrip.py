"""Acceptance: round-trip the real committed court export end to end (issue #154).

Every other test in the suite runs against a synthetic 1-2 page fixture. The
central invariant — a real Odyssey court zip extracted, ingested, exploded, and
re-imported byte-for-byte — was never exercised against real data despite the
17 MB ``intake/odyssey-250914566.zip`` sitting in the tree.

This module exercises that invariant against the committed fixture *as-is*
(the fixture is never edited). It is marked ``slow`` and excluded from the
default fast run (see ``[tool.pytest.ini_options]`` in pyproject.toml); run it
with ``pytest -m slow``. If the large fixture is absent the test skips with a
clear reason so contributors without it still get a green fast suite.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import lawnlord as main
from lawnlord.hashing import sha256_file

pytestmark = pytest.mark.slow

# The fixture lives at <repo>/intake/odyssey-250914566.zip; tests/ is one level
# under the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_ZIP = _REPO_ROOT / "intake" / "odyssey-250914566.zip"

# What the real export is known to contain (matches manifest.json / files/).
_EXPECTED_FILED_PDFS = 22
_EXPECTED_PORTAL_PAGES = 2


def _require_fixture() -> Path:
    if not _FIXTURE_ZIP.is_file():
        pytest.skip(
            f"real intake fixture not present at {_FIXTURE_ZIP} "
            "(large 17 MB export, not required for the fast suite)"
        )
    return _FIXTURE_ZIP


def _zip_manifest_hashes(zip_path: Path) -> dict[str, str]:
    """``files/...`` intake path -> declared sha256, read straight from the
    zip's own ``manifest.json`` (never the extracted copy on disk)."""
    with zipfile.ZipFile(zip_path) as zf:
        name = next(n for n in zf.namelist() if n.endswith("manifest.json"))
        manifest = json.loads(zf.read(name).decode("utf-8"))
    out: dict[str, str] = {}
    for entry in manifest.get("files") or []:
        if isinstance(entry, dict) and entry.get("path") and entry.get("sha256"):
            out[str(entry["path"])] = str(entry["sha256"])
    return out


def _build_case(zip_path: Path, dest_root: Path):
    """Extract + import + explode the real zip into ``dest_root``. Returns the
    extracted intake dir and the built case dir."""
    extracted = dest_root / "extracted-zip"
    main.extract_zip(zip_path, extracted)
    case_dir = dest_root / "case"
    main.main(["import", str(extracted), "--case-dir", str(case_dir)])
    main.main(["explode", "--case-dir", str(case_dir)])
    return extracted, case_dir


def _db_image_hashes(case_dir: Path) -> dict[str, str]:
    """intake_path -> sha256_hash recorded in DuckDB's images mirror."""
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        rows = con.execute("SELECT intake_path, sha256_hash FROM images").fetchall()
    finally:
        con.close()
    return {path: sha for path, sha in rows}


def test_real_zip_extracts_and_imports(tmp_path):
    """The committed fixture round-trips through the full pipeline as-is."""
    zip_path = _require_fixture()
    extracted, case_dir = _build_case(zip_path, tmp_path)

    assert (extracted / "data.json").is_file()
    assert (case_dir / "lawnlord.duckdb").is_file()


def test_stored_hashes_are_a_true_function_of_the_zip(tmp_path):
    """For every filed PDF: sha256 in DuckDB == sha256 of the extracted bytes ==
    the sha256 the zip's own manifest declared. The stored hash is the zip's
    hash, not a value regenerated independently."""
    zip_path = _require_fixture()
    extracted, case_dir = _build_case(zip_path, tmp_path)

    manifest_hashes = _zip_manifest_hashes(zip_path)
    db_hashes = _db_image_hashes(case_dir)

    assert manifest_hashes, "manifest declared no per-file hashes"
    assert len(manifest_hashes) == _EXPECTED_FILED_PDFS

    # Every manifest-declared file is mirrored, and the three hashes agree.
    for intake_path, manifest_sha in manifest_hashes.items():
        extracted_sha = sha256_file(extracted / intake_path)
        assert db_hashes.get(intake_path) == extracted_sha == manifest_sha, (
            f"hash divergence for {intake_path}"
        )

    # No extra/dropped rows: the DB mirrors exactly the manifest's files.
    assert set(db_hashes) == set(manifest_hashes)


def test_all_filed_pdfs_and_portal_pages_accounted_for(tmp_path):
    """All 22 filed PDFs and 2 portal pages from the export are present — row
    counts match the extracted directory, catching dropped/duplicated entries."""
    zip_path = _require_fixture()
    extracted, case_dir = _build_case(zip_path, tmp_path)

    on_disk_pdfs = sorted((extracted / "files").glob("*.pdf"))
    on_disk_pages = sorted((extracted / "pages").glob("*.html"))
    assert len(on_disk_pdfs) == _EXPECTED_FILED_PDFS
    assert len(on_disk_pages) == _EXPECTED_PORTAL_PAGES

    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        image_count = con.execute("SELECT count(*) FROM images").fetchone()[0]
        distinct_paths = con.execute(
            "SELECT count(DISTINCT intake_path) FROM images"
        ).fetchone()[0]
    finally:
        con.close()

    assert image_count == _EXPECTED_FILED_PDFS  # one row per filed PDF, no dupes
    assert distinct_paths == _EXPECTED_FILED_PDFS


def test_reimport_is_deterministic(tmp_path):
    """Extracting + ingesting the same zip twice yields identical DuckDB state:
    same row counts and same sha256 columns across every mirror table."""
    zip_path = _require_fixture()

    _, case_dir_a = _build_case(zip_path, tmp_path / "run-a")
    _, case_dir_b = _build_case(zip_path, tmp_path / "run-b")

    def snapshot(case_dir: Path) -> dict:
        con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
        try:
            counts = {
                t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in ("cases", "parties", "events", "images",
                          "image_events", "documents", "pages")
            }
            image_shas = con.execute(
                "SELECT sha256_hash FROM images ORDER BY sha256_hash"
            ).fetchall()
            page_shas = con.execute(
                "SELECT page_image_sha256 FROM pages ORDER BY page_image_sha256"
            ).fetchall()
        finally:
            con.close()
        return {"counts": counts, "image_shas": image_shas, "page_shas": page_shas}

    snap_a = snapshot(case_dir_a)
    snap_b = snapshot(case_dir_b)

    assert snap_a["counts"] == snap_b["counts"]
    assert snap_a["image_shas"] == snap_b["image_shas"]
    assert snap_a["page_shas"] == snap_b["page_shas"]
    # Sanity: the deterministic state actually carries the real data.
    assert snap_a["counts"]["images"] == _EXPECTED_FILED_PDFS
