# Lawnlord Project Context

> **Status — background vision.** This captures lawnlord's *prime directive and core concepts*. It
> is not the authoritative plan or status. Through **v0.3.0** the case-record foundation has shipped
> (exploder, DuckDB index, OCR, full-text search, lossless bundle). For what's shipped see
> [CHANGELOG](../CHANGELOG.md); for what's planned see [ROADMAP](ROADMAP.md) (the plan itself is the
> GitHub issues assigned to each milestone). The commit is always the present.

## Overview

Lawnlord is a personal legal intelligence system designed for a single user.

The goal is not document management.

The goal is to understand legal issues well enough to generate exceptional filings.

Lawnlord transforms a collection of legal files into a structured, searchable, analyzable case graph that can be used for legal research, strategy development, evidence analysis, and filing generation.

---

# Prime Directive

Win by understanding the legal issues well enough to generate exceptional filings.

Lawnlord exists to help the user develop a complete understanding of a case before drafting any legal document.

The system's primary objective is not document generation.

It is legal understanding.

Before generating any filing, the system should understand:

- What happened
- What can be proven
- What law applies
- What should be done next

Understanding precedes strategy.

Strategy precedes drafting.

Drafting is the final output of understanding.

Every generated statement should be traceable to:

- Source evidence
- Source artifacts
- Legal authority
- Procedural context

---

# Core Concepts

## Case Artifacts

Artifacts are case-specific materials.

Examples:

- Petitions
- Motions
- Orders
- Discovery
- Exhibits
- Emails
- Text messages
- Photos
- Audio recordings
- Correspondence

Artifacts are immutable.

Original files always remain the source of truth.

---

## Knowledge Base

The Knowledge Base contains information used to interpret artifacts.

Examples:

- Statutes
- Case law
- Rules of civil procedure
- Local court rules
- Pro se guidance
- Practice manuals
- Legal research
- Strategy notes

Artifacts are evidence.

Knowledge Base documents are authority and context.

---

# Artifact Decomposition

The system does not treat documents as monolithic files.

Every artifact is exploded into discrete legal entities.

Examples:

- Facts
- Events
- Claims
- Allegations
- Evidence references
- Citations
- Legal arguments
- Requested relief
- Court orders
- Deadlines
- Procedural actions

Every extracted entity must maintain provenance back to:

- Artifact
- Page
- Paragraph
- Text span

Example:

```json
{
  "entity_type": "fact",
  "source_artifact": "MotionForSummaryJudgment.pdf",
  "page": 12,
  "paragraph": 4,
  "confidence": 0.98
}
```

---

# Case Graph

The system should build a graph of relationships.

Examples:

Fact
→ supported by → Evidence

Claim
→ supported by → Facts

Claim
→ governed by → Statute

Statute
→ interpreted by → Case Law

Evidence
→ contained in → Artifact

The graph becomes the foundation for reasoning and drafting.

---

# Architecture Direction

Single-user.

Local-first.

No SaaS requirements.

No multi-tenant requirements.

Current preferred architecture:

Filesystem + DuckDB.

Structure:

case/
├── intake/
├── artifacts/
├── knowledgebase/
├── extracted/
├── analysis/
├── outputs/
├── manifests/
└── lawnlord.duckdb

DuckDB stores:

- Entities
- Relationships
- Metadata
- Provenance
- Analysis results

Filesystem stores:

- Original artifacts
- Knowledge Base files
- Outputs
- Manifests

---

# User Workflow

1. Create Case
2. Drop files into intake folder
3. System classifies files
4. OCR and text extraction
5. Artifact decomposition
6. Entity creation
7. Relationship mapping
8. Knowledge Base linking
9. Analysis generation
10. Strategy generation
11. Filing generation

---

# Analysis Capabilities

The system should answer:

- What happened?
- What evidence supports this fact?
- Which claims lack evidence?
- Which facts are disputed?
- What deadlines exist?
- What law applies?
- What procedural issues exist?
- What filings should be considered next?

---

# Strategy Capabilities

The system should identify:

- Strong arguments
- Weak arguments
- Missing evidence
- Procedural risks
- Litigation opportunities
- Research opportunities
- Potential motions
- Likely defenses

---

# Drafting Capabilities

The system should generate:

- Motions
- Responses
- Pleadings
- Discovery requests
- Timelines
- Evidence matrices
- Research memoranda
- Case summaries

Every generated statement must be supported by:

- Evidence
- Facts
- Legal authority
- Procedural context

---

# Important Design Principle

Lawnlord is not a filing generator.

Lawnlord is an understanding engine whose primary output happens to be filings.

The measure of success is not the number of documents generated.

The measure of success is the quality of understanding developed before drafting.
