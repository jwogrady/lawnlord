# The case-record schema (developer code summary)

> **Provable from the code and the zip.** The intake schema is whatever the zip's own `schema.json`
> declares over its `data.json`; the in-memory contract is `models.CaseModel`; the index is what
> `db.py` creates. If this doc and any of those disagree, **they win** — fix the doc. Below-the-image
> decomposition (page explosion, AI transcription, spatial anchoring) ships today; the analysis layer
> on top is future work — see the [ROADMAP](../ROADMAP.md).

The single source of truth is the **deterministic intake zip** (`rake`). There is no separate
canonical `case.json` standard anymore — `data.json`, described by the zip's bundled `schema.json`,
**is** the standard. lawnlord reads that record into a typed `CaseModel` and derives a DuckDB index
from it.

## The intake zip

```text
data.json      the case record (array of one case object)
schema.json    JSON Schema (draft 2020-12) describing data.json — self-describing
manifest.json  per-file sha256 + source ViewDocumentFragment URLs + capture metadata
files/         the filed PDFs (doc-<DocumentFragmentID>.pdf)
pages/         the captured portal HTML (CaseDetail.html, CaseDocuments.html)
```

`data.json` (top-level keys per case): `caseNumber`, `caseType`, `dateFiled`, `location`, `parties`,
`financial`, `documents`, `registerOfActions`.

- **`documents[]`** — one filed PDF each: `Image` (title), `Page Count`, `file` (`files/doc-N.pdf`),
  `date`, `event`, `events[]`. Values are scrape-faithful strings.
- **`registerOfActions[]`** — `date`, `event`, `section` (`dispositions` | `other events and
  hearings`), and `documents[]` (file paths joining back to `documents[]`).
- **`parties[]`** — `name`, `role`, `representation[]`.
- **`financial`** — `assessedTo`, `balanceAsOf`, `balanceDue`, `totalAssessment`, `totalPayments`,
  `transactions[]{date, description, amount}` (the plaintiff's court costs, not the owed ledger).

## Vocabulary

| Term | Meaning |
|---|---|
| **case** | the lawsuit |
| **event** | a docket entry / register-of-actions row |
| **image** | a **filed PDF** — the court's leaf; the Actual view ends here |
| **document** | a logical document *within* an image (Motion, Exhibit A…) — surfaced by the Exploded view (`explode.py`); not present in the zip. Boundary detection starts simple: one document per image today |
| **page** | a page of a filed PDF |

## The in-memory contract (`models.py`, `CaseModel`)

The zip reader (`reader.load_case_model`) populates this; `ingest.py` consumes it.

- **`identity`** (`CaseIdentity`) — `case_number`, `title`, `court`, `judicial_officer`, `case_type`,
  `status`, `date_filed`, `disposition_*`, `citation_number`, `source_url`, … (curated fields the
  reader lifts from `data.json` + the captured `pages/*.html`).
- **`parties[]`** (`Party`) — `role`, `name`, `representation`, `location`, `attorneys[]`, `aliases`.
- **`events[]`** (`Event`) — `date`, `phase`, `event`, `description`, `party`, `files[]`.
- **`documents[]`** (`DocumentRef`) — `intake_path` (`files/doc-N.pdf`), `filename`, `title`,
  `declared_page_count`, `docket_event`, `filing_date`, `source_url` (the per-file portal `url`,
  empty when absent — never fabricated; persisted to `images.source_url`).
- **`financials`** (`Financials`, nullable) and `hearings` / `docket` / `case_flags` /
  `case_cross_references` / `source_note` carry the remaining structure.

## DuckDB index (`db.py`, `SCHEMA_VERSION = 12`)

A derived, regenerable index over the record. The `_SCHEMA_STATEMENTS` tuple creates exactly twelve
tables, in three layers (read `db.py` for exact columns):

- **Bookkeeping** — `schema_meta` (the stamped schema version).
- **Mirror** (populated by `ingest.py` from the `CaseModel`) — `cases`, `parties`, `financials`,
  `financial_transactions`, `events`, `images`, `image_events`.
- **Exploded layer** (additive; references the mirror, never mutates it) — `documents` (one per image)
  and `pages` (one per rendered page, with its PNG pointer), populated by `explode.py`; `page_text`,
  the append-only AI transcription per page keyed on a content-hash `id` so a page holds *every*
  variation (the PDF text layer plus one row per vision model; ADR-0005), populated by `transcribe.py`;
  and `page_regions`, normalized bounding boxes per text span anchored via `(anchor_kind, anchor_id)`
  (ADR-0009), populated by `regions.py`.

Per-case DBs are regenerable, so a `SCHEMA_VERSION` bump needs no in-place migration — `apply_schema`
refuses a stamped-version mismatch and the fix is always to re-import.

DuckDB enforces **a single read-write process per case file**, and refuses a read-only open too while a
writer holds the lock — so a case cannot be viewed or queried *during* an active write (ADR-0003). All
opens go through `db.open_case_db`, which surfaces lock contention as a clear `CaseDatabaseBusy` error
(naming the case path) rather than a raw DuckDB `IOException`. Run a case's write commands
(`import`/`explode`/`transcribe`/`regions`) serially and read it only once they finish.

## Additive-only invariant

The mirrored record — the zip and its provenance (sha256s, paths, page counts) — is immutable.
Anything lawnlord derives (the DuckDB index, the Exploded/transcription/region layers) is additive and
may never alter it. The zip is the chokepoint: same input → same bytes, verified against
`manifest.json`.
