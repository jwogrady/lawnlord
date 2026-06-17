"""Curated-metadata overlay (corpus-curation.json).

Loads the optional curation file and applies it during a build. Only the
ALLOWED_CURATED_FIELDS whitelist can be overridden; provenance, page ranges,
hashes, slugs, tier/confidence, paths, and citations are always generated and
can never be overridden by an overlay.
"""

from __future__ import annotations

import json
from pathlib import Path

from .console import console

# The only fields a curation overlay may set. Provenance, page ranges,
# hashes, slugs, boundary tier/confidence, paths, and citations are always
# generated and can never be overridden.
ALLOWED_CURATED_FIELDS = {
    "submissionType",
    "filingParty",
    "courtOrAgency",
    "caseNumber",
    "tags",
    "notes",
    "needsHumanReview",
    "reviewNotes",
    "status",
}


def load_curation(path: Path) -> dict:
    """Load the optional curated-metadata overlay from the given path.
    Returns {} when absent or unparseable; a bad file never crashes the
    build, it only loses the overlay."""
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level must be an object")
    except Exception as exc:
        console.print(f"[red]Could not parse {path}: {exc} — ignoring curation.[/]")
        return {}

    console.print(f"[bold]Curation:[/] {path}")
    return data


def document_curation_for(
    curation: dict, document_slug: str, source_zip_path: str, original_filename: str
) -> dict:
    """Curated document entries are keyed by documentSlug (preferred), with
    sourceZipPath/originalFilename accepted as fallbacks."""
    documents = curation.get("documents")
    if not isinstance(documents, dict):
        return {}
    for key in (document_slug, source_zip_path, original_filename):
        value = documents.get(key)
        if isinstance(value, dict):
            return value
    return {}


def section_curation_for(
    document_curation: dict, section_slug: str, section_id: str, title: str
) -> dict:
    """Curated section entries are keyed by sectionSlug (preferred), with
    sectionId/title accepted as fallbacks."""
    sections = document_curation.get("sections")
    if not isinstance(sections, dict):
        return {}
    for key in (section_slug, section_id, title):
        if not key:
            continue
        value = sections.get(key)
        if isinstance(value, dict):
            return value
    return {}


def apply_metadata_overlay(base: dict, overlay: dict, allowed_fields: set[str]) -> bool:
    """Copy only allowed curated fields onto base; unknown fields are
    ignored, so an overlay can never remove or replace generated provenance.
    tags must stay a list of strings (invalid values are skipped). Returns
    True when at least one field was applied."""
    applied = False
    for field_name in sorted(allowed_fields):
        if field_name not in overlay:
            continue
        value = overlay[field_name]
        if field_name == "tags":
            if not isinstance(value, list):
                continue
            value = [str(v) for v in value]
        base[field_name] = value
        applied = True
    return applied
