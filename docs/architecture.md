# Lawnlord Architecture

> **Status — background vision.** This sketches lawnlord's *target architecture*; it is not the
> authoritative plan or status. Through **v0.3.0** the case-record foundation has shipped (exploder,
> DuckDB index `case → event → image → document → page`, OCR, full-text search, lossless bundle).
> The entity graph, relationships, and analysis/strategy/drafting layers below are **additive**
> future work, sequenced in the prerequisite chain. For what's shipped see
> [CHANGELOG](../CHANGELOG.md); for what's planned — and the GitHub issues that *are* the plan — see
> [ROADMAP](ROADMAP.md). The commit is always the present.

## Overview

Lawnlord is a local-first legal intelligence system.

It transforms raw legal files into structured case knowledge by separating source materials, legal reference materials, extracted entities, relationships, analysis, strategy, and generated filings.

The architecture should support one primary objective:

> Understand the legal issues deeply enough to generate exceptional filings.

---

# Architectural Model

Lawnlord is built around a self-contained case workspace.

```text
case/
├── intake/
├── artifacts/
├── knowledgebase/
├── extracted/
├── analysis/
├── outputs/
├── manifests/
└── lawnlord.duckdb
```

Each case is portable, inspectable, and locally owned.

No critical case information should exist only inside an opaque service.

---

# Core Layers

## 1. File System Layer

The filesystem stores the actual case materials.

It is the physical container for:

- Raw uploads
- Original artifacts
- Knowledge Base files
- Generated outputs
- JSON manifests
- Extracted text
- Analysis reports

The filesystem should remain human-readable.

A user should be able to open a case folder and understand its structure without needing the app.

---

## 2. Intake Layer

The intake layer receives new files.

Input examples:

```text
MotionToDismiss.pdf
CourtOrder.pdf
ExhibitA.pdf
Emails.zip
Photos.zip
TextMessages.csv
```

The intake pipeline performs:

1. File detection
2. File classification
3. Deduplication
4. OCR
5. Text extraction
6. Metadata extraction
7. Artifact registration
8. Manifest generation

The user should not manually organize files.

Lawnlord decides where each file belongs.

---

## 3. Artifact Layer

Artifacts are immutable case-specific source records.

Examples:

- Filings
- Motions
- Orders
- Exhibits
- Emails
- Text messages
- Photos
- Discovery responses
- Correspondence

Artifacts are evidence or procedural records.

They are never overwritten.

Every extracted entity must trace back to an artifact.

---

## 4. Knowledge Base Layer

The Knowledge Base stores legal reference material.

Examples:

- Statutes
- Rules of civil procedure
- Local court rules
- Case law
- Pro se guides
- Practice manuals
- Research notes
- Strategy notes

Knowledge Base materials are not evidence.

They provide authority, context, procedure, and strategy.

The system must keep artifacts and Knowledge Base materials separate.

---

## 5. Extraction Layer

The extraction layer converts files into machine-readable content.

Outputs may include:

```text
extracted/
├── text/
├── markdown/
├── ocr/
├── chunks/
└── entities/
```

Extraction should preserve provenance.

Each extracted chunk should know:

- Source file
- Page
- Paragraph
- Text span
- Extraction method
- Confidence score

Example:

```json
{
  "artifact_id": "artifact_001",
  "source_file": "MotionToDismiss.pdf",
  "page": 8,
  "paragraph": 3,
  "text": "Plaintiff failed to state a claim...",
  "extraction_method": "pdf_text",
  "confidence": 0.97
}
```

---

## 6. Entity Layer

> **Additive, post-readiness-gate (v0.6.0+).** The entity layer is *not* part of the mirrored court
> record. It begins only after the "is" layer is canonical (every page reconstructable text). Every
> entity is a machine **proposal** carrying provenance (artifact/page/paragraph/span) and
> `needsReview: true` — accepted or declined by a human; only accepted entities are treated as truth
> (issue #28).

Documents are decomposed into discrete legal entities.

Core entities include:

- Case
- Artifact
- Knowledge Document
- Party
- Fact
- Event
- Claim
- Cause of Action
- Allegation
- Evidence Item
- Exhibit
- Citation
- Statute
- Rule
- Court Order
- Deadline
- Argument
- Requested Relief
- Procedural Action
- Witness

Entities are stored in DuckDB.

Each entity must preserve provenance.

---

## 7. Relationship Layer

Entities are linked into a case graph.

Example relationships:

```text
Fact → supported by → Evidence
Fact → contradicted by → Evidence
Claim → supported by → Fact
Claim → governed by → Statute
Argument → cites → Citation
Filing → requests → Relief
Court Order → creates → Deadline
Event → supported by → Artifact
```

The relationship layer surfaces connections for the human to reason across the case. Like the entity
layer, every relationship is an additive, accept/decline proposal (v0.6.0+) — never a
machine-rendered legal conclusion.

This is where the work moves from file organization to *assisted* legal understanding: the human's
understanding, supported by the graph.

---

## 8. DuckDB Layer

DuckDB is the local structured database.

It stores:

- Case metadata
- Artifact registry
- Knowledge Base registry
- Extracted chunks
- Entities
- Relationships
- Provenance
- Analysis results
- Strategy outputs
- Draft metadata

DuckDB is ideal for the first version because Lawnlord is single-user, local-first, portable, and analysis-heavy.

DuckDB should not replace the filesystem.

It should index, relate, and analyze what exists in the filesystem.

---

# Data Flow

```text
User adds files
    ↓
Intake pipeline
    ↓
File classification
    ↓
OCR / text extraction
    ↓
Artifact or Knowledge Base registration
    ↓
Chunking
    ↓
Entity extraction
    ↓
Relationship mapping
    ↓
Case graph creation
    ↓
Analysis generation
    ↓
Strategy generation
    ↓
Draft generation
```

---

# Case Workspace Structure

## intake/

Temporary landing area for new files.

```text
intake/
├── pending/
├── processing/
├── failed/
└── completed/
```

## artifacts/

Immutable case records.

```text
artifacts/
├── filings/
├── orders/
├── exhibits/
├── discovery/
├── correspondence/
├── communications/
├── media/
└── other/
```

## knowledgebase/

Legal authority and context.

```text
knowledgebase/
├── statutes/
├── rules/
├── cases/
├── procedures/
├── pro-se-guides/
├── research-notes/
└── strategy-notes/
```

## extracted/

Machine-readable derivatives.

```text
extracted/
├── text/
├── markdown/
├── ocr/
├── chunks/
└── entities/
```

## analysis/

Generated legal analysis.

```text
analysis/
├── timelines/
├── evidence-maps/
├── claim-analysis/
├── contradiction-reports/
├── gap-analysis/
├── procedural-analysis/
└── strategy/
```

## outputs/

Generated filings and deliverables.

```text
outputs/
├── drafts/
├── motions/
├── responses/
├── discovery/
├── summaries/
└── exports/
```

## manifests/

Portable JSON metadata.

```text
manifests/
├── case.json
├── artifacts.json
├── knowledgebase.json
├── entities.json
├── relationships.json
└── analysis.json
```

---

# Suggested DuckDB Tables

## cases

Stores case-level metadata.

```sql
cases (
  id,
  name,
  court,
  cause_number,
  jurisdiction,
  created_at,
  updated_at
)
```

## artifacts

Stores immutable case records.

```sql
artifacts (
  id,
  case_id,
  filename,
  file_path,
  artifact_type,
  sha256_hash,
  date_received,
  source,
  created_at
)
```

## knowledge_documents

Stores reference materials.

```sql
knowledge_documents (
  id,
  case_id,
  filename,
  file_path,
  knowledge_type,
  jurisdiction,
  source,
  created_at
)
```

## chunks

Stores extracted text chunks.

```sql
chunks (
  id,
  case_id,
  source_type,
  source_id,
  text,
  page_number,
  paragraph_number,
  text_span_start,
  text_span_end,
  extraction_method,
  confidence,
  created_at
)
```

## entities

Stores extracted legal entities.

```sql
entities (
  id,
  case_id,
  entity_type,
  title,
  text,
  source_chunk_id,
  source_artifact_id,
  confidence,
  created_at
)
```

## relationships

Stores case graph edges.

```sql
relationships (
  id,
  case_id,
  from_entity_id,
  relationship_type,
  to_entity_id,
  confidence,
  created_at
)
```

## citations

Stores legal citations.

```sql
citations (
  id,
  case_id,
  citation_text,
  authority_type,
  jurisdiction,
  source_entity_id,
  validation_status,
  created_at
)
```

## deadlines

Stores procedural deadlines.

```sql
deadlines (
  id,
  case_id,
  title,
  due_date,
  source_artifact_id,
  source_entity_id,
  status,
  created_at
)
```

## analysis_results

Stores generated analysis.

```sql
analysis_results (
  id,
  case_id,
  analysis_type,
  title,
  summary,
  result_json,
  created_at
)
```

---

# Search Architecture

Lawnlord should support three types of search.

## Exact Search

Useful for names, dates, citations, and phrases.

Example:

```text
Find every mention of "notice to vacate".
```

## Semantic Search

Useful for meaning-based retrieval.

Example:

```text
Show evidence supporting retaliation.
```

## Relationship Search

Useful for graph-based reasoning.

Example:

```text
Which facts support Claim 3?
```

The first version can start with DuckDB queries and text search.

Embeddings can be added later.

---

# AI Agent Architecture

> **Agents are execution tools, not decision-makers.** They handle deterministic, repeatable work —
> classify, OCR, chunk, extract, compute timelines, draft. Anything an agent produces about the law
> or strategy is a **proposal** the human accepts or declines (issue #28); legal conclusions are
> never machine-rendered. The Research / Analysis / Strategy agents below *surface* candidates and
> *flag* gaps — they do not decide. The human decides.

Lawnlord can be organized around specialized agents.

## Intake Agent

Responsible for:

- Classifying files
- Detecting duplicates
- Routing files
- Creating manifests

## Extraction Agent

Responsible for:

- OCR
- Text extraction
- Chunking
- Metadata extraction

## Entity Agent

Responsible for extracting:

- Facts
- Events
- Claims
- Arguments
- Citations
- Evidence
- Deadlines

## Research Agent

Responsible for:

- Connecting facts to law
- Finding relevant authorities
- Summarizing legal standards
- Flagging missing authority

## Analysis Agent

Responsible for:

- Timelines
- Evidence maps
- Contradiction analysis
- Gap analysis
- Procedural analysis

## Strategy Agent

Responsible for:

- Recommended actions
- Motion opportunities
- Risk identification
- Argument strength assessment

## Drafting Agent

Responsible for:

- Motions
- Responses
- Discovery requests
- Summaries
- Filing drafts

## Review Agent

Responsible for:

- Citation checking
- Evidence support checking
- Procedural consistency
- Hallucination reduction

---

# Drafting Pipeline

Drafting should happen only after analysis.

```text
Question
  ↓
Relevant facts
  ↓
Supporting evidence
  ↓
Relevant law
  ↓
Procedural posture
  ↓
Strategy
  ↓
Draft
  ↓
Review
  ↓
Final output
```

Every generated statement should be traceable.

No filing should contain unsupported factual claims or unverified legal citations.

---

# Provenance Requirement

Every important output must answer:

```text
Where did this come from?
```

For facts:

- Artifact
- Page
- Paragraph
- Text span

For law:

- Statute
- Rule
- Case citation
- Jurisdiction
- Source document

For strategy:

- Facts relied on
- Evidence relied on
- Law relied on
- Procedural posture

This is non-negotiable.

---

# Local-First Design Principles

Lawnlord should be:

- Portable
- Private
- Inspectable
- Backup-friendly
- Single-user first
- Filesystem-native
- Database-assisted
- AI-enhanced, not AI-dependent

The user should always own the case folder.

---

# MVP Architecture

The first build should focus on:

1. Create case workspace
2. Add files to intake
3. Classify files as artifact or Knowledge Base
4. Extract text
5. Store artifact registry in DuckDB
6. Store chunks in DuckDB
7. Extract basic entities
8. Generate case summary
9. Generate timeline
10. Generate evidence map
11. Generate first draft output

Avoid overbuilding.

No multi-user auth.

No cloud sync.

No CockroachDB.

No complex distributed architecture.

---

# Future Architecture

Possible future additions:

- Local embeddings
- Vector search
- Citation validation
- Court-rule automation
- Deadline calculator
- PDF annotation
- Exhibit bundle generation
- Multi-case knowledge reuse
- GUI dashboard
- Agent orchestration
- Filing template engine
- Export to Word/PDF
- Optional encrypted cloud backup

---

# Architecture Success Criteria

The architecture succeeds if Lawnlord can:

1. Preserve original evidence.
2. Separate artifacts from legal knowledge.
3. Explode documents into legal entities.
4. Link entities into a case graph.
5. Trace every conclusion back to source materials.
6. Generate strategy from evidence and law.
7. Generate filings grounded in facts, citations, and procedure.

The architecture fails if it merely stores documents.

Lawnlord is not a document repository.

It is a local legal understanding engine.
