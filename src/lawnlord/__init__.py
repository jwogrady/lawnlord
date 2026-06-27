"""lawnlord: build a queryable case index from the deterministic intake zip.

The intake standard is the zip produced by ``jwogrady/rake`` (schema.json +
data.json + files/ + pages/). It is the single source of truth; DuckDB is built
from it to back the viewer. Everything additive (analysis, AI layers, document
explosion, multi-provider merging, reconstruction) has been removed — the
package now mirrors the zip's views and nothing more.

This module re-exports the public API as a flat surface so callers and tests can
``import lawnlord`` and reach every symbol regardless of which module owns it.
"""

from __future__ import annotations

from .cli import main
from .console import console
from .db import (
    SCHEMA_VERSION,
    CaseDatabaseBusy,
    SchemaVersionMismatch,
    apply_schema,
    open_case_db,
)
from .explode import explode_case
from .export import (
    export_actual,
    export_document,
    export_exploded,
    export_filing,
    export_image,
    export_metrics,
    export_page,
    export_regions,
)
from .hashing import now_iso, sha256_bytes, sha256_file
from .ingest import ManifestHashMismatch, ingest_case
from .intake import (
    CONFIG_FILENAME,
    DEFAULT_CORPUS_DIRNAME,
    DEFAULT_INTAKE_DIRNAME,
    Intake,
    load_intake,
    resolve_packet,
    scaffold,
)
from .models import (
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
    PdfEntry,
    SectionBoundary,
    case_slug,
    is_suspicious_entry,
    unique_slug,
)
from .models import FILES_DIRNAME
from .reader import (
    captured_at,
    extract_zip,
    find_intake_dir,
    load_case_model,
    manifest_declared_hashes,
    validate_data,
)
from .regions import (
    capture_pdf_regions,
    extract_pdf_charboxes,
    normalize_rect,
    token_char_offsets,
)
from .transcribe import DEFAULT_MODEL as TRANSCRIBE_MODEL
from .transcribe import (
    CloudTranscriber,
    LocalTranscriber,
    escalate_case,
    extract_pdf_text,
    installed_vision_models,
    measure_case,
    ollama_available,
    transcribe_case,
    transcribe_page,
)
from .workspace import OUTPUT_SUBDIRS, Case
