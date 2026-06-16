"""Repo layout, source-archive resolution, and curated-input filenames.

REPO_ROOT is derived from this file's location (src/lawnlord/paths.py, three
parents up).

NOTE (decoupling pending): input resolution below (FILINGS_DIR,
DEFAULT_ZIP_CANDIDATES, the curated-input filenames) is still anchored to a
fixed repo layout — a holdover from when this tool lived inside the case repo.
The standalone-tool model points lawnlord at an *intake folder* supplied on
the CLI (the `lawnlord start` scaffold), not a hardcoded path. Until that
lands, a run outside an intake simply finds no packet (and the baseline test
skips).
"""

from __future__ import annotations

from pathlib import Path

from .console import console

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FILINGS_DIR = REPO_ROOT / "src" / "filings"  # record PDFs + curated metadata inputs
DEFAULT_CORPUS_DIR = REPO_ROOT / "dist" / "corpus"  # generated, gitignored

# Searched in order when no zip path is given. The canonical, tracked source
# archive for case 25-09-14566 is src/filings/E222C7C4.zip. The cwd-relative
# fallbacks are for local/manual runs only (e.g. from src/ or the repo root); do
# not commit a second repo-root source archive.
DEFAULT_ZIP_CANDIDATES = [
    REPO_ROOT / "src" / "filings" / "E222C7C4.zip",
    Path("E222C7C4.zip"),
    Path("../E222C7C4.zip"),
]

# Curated inputs live in src/filings/ (the canonical record folder). Both files
# are optional and are the committed source of truth for boundaries/metadata.
MANUAL_BOUNDARIES_FILENAME = "bundle-boundaries.json"

# Generated draft emitted by --emit-boundary-template. Gitignored and never
# read by detection; a human reviews it and copies the result to
# MANUAL_BOUNDARIES_FILENAME to make it live.
GENERATED_BOUNDARIES_FILENAME = "bundle-boundaries.generated.json"

# Curated metadata overlay (Feature 10). The committed source of truth for
# curated document/section metadata; generated corpus JSON stays fully
# regenerable from it.
CURATION_FILENAME = "corpus-curation.json"


def resolve_zip_path(arg_value: str | None) -> Path:
    if arg_value:
        zip_path = Path(arg_value).resolve()
        if not zip_path.exists():
            raise FileNotFoundError(zip_path)
        return zip_path

    for candidate in DEFAULT_ZIP_CANDIDATES:
        if candidate.exists():
            return candidate.resolve()

    console.print("[red]No ZIP found. Pass a path, or place the archive at one of:[/]")
    for candidate in DEFAULT_ZIP_CANDIDATES:
        console.print(f"  - {candidate}")
    raise SystemExit(1)
