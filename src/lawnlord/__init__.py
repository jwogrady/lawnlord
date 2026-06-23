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
from .db import SCHEMA_VERSION, apply_schema, open_case_db
from .explode import explode_case
from .export import export_actual, export_exploded
from .hashing import now_iso, sha256_bytes, sha256_file
from .ingest import ingest_case
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
    validate_data,
)
from .transcribe import DEFAULT_MODEL as TRANSCRIBE_MODEL
from .transcribe import (
    CloudTranscriber,
    LocalTranscriber,
    extract_pdf_text,
    ollama_available,
    transcribe_case,
    transcribe_page,
)
from .workspace import OUTPUT_SUBDIRS, Case
