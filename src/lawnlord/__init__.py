"""lawnlord: a zip -> five-level legal-corpus generator.

Logic is split across focused modules (intake, hashing, models, boundaries,
curation, preservation, analysis_schema, archive, corpus, reporting, cli).
This package re-exports their public API as a flat surface so callers and
tests can ``import lawnlord`` and reach every symbol, regardless of which
module owns it.
"""

from __future__ import annotations

from .analysis_schema import legal_analysis_placeholders, write_json
from .archive import inspect_archive, inspect_folder, inspect_source, is_suspicious_entry
from .assemble import assemble_case
from .bundle import bundle_case
from .canonical import SCHEMA_VERSION as CANONICAL_SCHEMA_VERSION
from .canonical import from_canonical, to_canonical
from .pack import pack_case
from .boundaries import (
    CONFIDENCE_BOOKMARK,
    CONFIDENCE_FALLBACK,
    CONFIDENCE_FRONT_MATTER,
    CONFIDENCE_HEADING,
    CONFIDENCE_MANUAL,
    CONFIDENCE_UNTRUSTED_BOOKMARK,
    FILENAME_LIKE_BOOKMARK_RE,
    HEADING_DANGLING_WORDS,
    HEADING_MAX_CHARS,
    HEADING_MAX_WORDS,
    HEADING_MINOR_WORDS,
    HEADING_SCAN_LINES,
    LEGAL_BOUNDARY_PATTERNS,
    REVIEW_CONFIDENCE_THRESHOLD,
    TIER_BOOKMARKS,
    TIER_FALLBACK,
    TIER_HEADING_SCAN,
    TIER_MANUAL,
    build_sections,
    clean_title,
    confidence_distribution,
    covers_exactly,
    detect_sections_in_doc,
    finalize_slugs,
    find_heading_boundary,
    get_page_text,
    is_probable_heading_line,
    legal_keyword_family,
    load_manual_boundaries,
    manual_entries_for,
    normalize_heading_candidate,
    section_summary,
    sections_from_manual,
    uppercase_letter_ratio,
)
from .console import console
from .corpus import (
    document_manifest_entry,
    explode_document,
    manifest_section_entry,
    submission_entry_from_existing,
    submission_manifest_entry,
    write_corpus,
)
from .curation import (
    ALLOWED_CURATED_FIELDS,
    apply_metadata_overlay,
    document_curation_for,
    load_curation,
    section_curation_for,
)
from .db import SCHEMA_VERSION, apply_schema, open_case_db
from .hashing import now_iso, sha256_bytes, sha256_file
from .index import index_corpus
from .ingest import ingest_case
from .intake import (
    CONFIG_FILENAME,
    CURATION_FILENAME,
    DEFAULT_CORPUS_DIRNAME,
    DEFAULT_INTAKE_DIRNAME,
    GENERATED_BOUNDARIES_FILENAME,
    MANUAL_BOUNDARIES_FILENAME,
    Intake,
    load_intake,
    resolve_packet,
    scaffold,
)
from .models import PdfEntry, SectionBoundary, unique_slug
from .ocr import DEFAULT_OCR_DPI, make_lazy_ocr, make_ocr, ocr_image
from .preservation import (
    PRESERVED_LEGAL_FIELDS,
    PRESERVED_REVIEW_METADATA_FIELDS,
    apply_preserved_analysis,
    collect_reviewed_analysis,
    is_reviewed_analysis,
    preservation_exact_key,
    preservation_fallback_key,
)
from .providers import (
    FILINGS_DIRNAME,
    PROVIDERS,
    Attorney,
    CaseIdentity,
    CaseModel,
    DocketDocument,
    DocketEntry,
    DocumentRef,
    Event,
    Financials,
    FinancialTransaction,
    Hearing,
    Party,
    case_slug,
    parse_combo,
    parse_odyssey,
    parse_provider,
)
from .query import (
    images_by_event,
    images_by_party,
    images_by_phase,
    needs_review_documents,
    search_text,
)
from .reporting import report_archive, write_boundary_template
from .unify import (
    find_gaps,
    normalize_date,
    present_sources,
    source_provenance,
    unify,
)
from .workspace import OUTPUT_SUBDIRS, Case
