# The case-record schema (developer code summary)

> **Provable from the code and the zip.** The intake schema is whatever the zip's own `schema.json`
> declares over its `data.json`; the in-memory contract is `models.CaseModel`; the index is what
> `db.py` creates. If this doc and any of those disagree, **they win** — fix the doc. Below-the-image
> decomposition and analysis are future work — see the [ROADMAP](../ROADMAP.md).

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
| **document** | a logical document *within* an image (Motion, Exhibit A…) — surfaced by the future Exploded view, not present in the zip |
| **page** | a page of a filed PDF |

## The in-memory contract (`models.py`, `CaseModel`)

The zip reader (next branch) populates this; `ingest.py` consumes it.

- **`identity`** (`CaseIdentity`) — `case_number`, `title`, `court`, `judicial_officer`, `case_type`,
  `status`, `date_filed`, `disposition_*`, `citation_number`, `source_url`, … (curated fields the
  reader lifts from `data.json` + the captured `pages/*.html`).
- **`parties[]`** (`Party`) — `role`, `name`, `representation`, `location`, `attorneys[]`, `aliases`.
- **`events[]`** (`Event`) — `date`, `phase`, `event`, `description`, `party`, `files[]`.
- **`documents[]`** (`DocumentRef`) — `intake_path` (`files/doc-N.pdf`), `filename`, `title`,
  `declared_page_count`, `docket_event`, `filing_date`.
- **`financials`** (`Financials`, nullable) and `hearings` / `docket` / `case_flags` /
  `case_cross_references` / `source_note` carry the remaining structure.

## DuckDB index (`db.py`, `SCHEMA_VERSION = 6`)

A derived, regenerable index over the record. Populated today: `cases`, `parties`, `financials`,
`financial_transactions`, `events`, `images`, `image_events`. Present but **not yet populated** (to
be re-scoped to the zip's level): `documents`, `chunks`, `extracted_dates`, `knowledge_documents`.
Read `db.py` `_SCHEMA_STATEMENTS` for exact columns.

## Additive-only invariant

The mirrored record — the zip and its provenance (sha256s, paths, page counts) — is immutable.
Anything lawnlord derives (the DuckDB index, future analysis) is additive and may never alter it. The
zip is the chokepoint: same input → same bytes, verified against `manifest.json`.
