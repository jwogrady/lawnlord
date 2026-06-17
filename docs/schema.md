# The standard court-record schema (developer code summary)

> **Provable from the code.** Every field below is what `canonical.to_canonical()` (`canonical.py`)
> actually produces and what `db.py` actually creates. If this doc and the code disagree, **the code
> wins.** Below-the-image decomposition and analysis are future work — see the
> [ROADMAP](../ROADMAP.md).

Lawnlord mirrors the court record from the Odyssey (`ody`) and re:SearchTX (`txe`) portals into one
canonical `case.json`. The two portals are two views of the same record; lawnlord normalizes them
into one shape and tags which source supplied each field.

## `case.json` (`schemaVersion` `"2.0"`, `canonical.py`)

Root keys: `schemaVersion`, `provider`, `case`, `parties`, `financials` (nullable), `hearings`,
`events`, `docket`, `documents`, `caseFlags`, `caseCrossReferences`, `sourceNote`, plus the derived
`sources`, `provenance`, and `gaps`.

- **`case`** — `caseNumber`, `title`, `court`, `clerk`, `judicialOfficer`, `caseType`,
  `caseCategory`, `status`, `dateFiled`, `citationNumber`,
  `disposition{type, date, comment, judicialOfficer}`, `sourceUrl` (a single URL), `lastRefreshed`.
- **`parties[]`** — `role`, `name`, `representation`, `location`, `aliases[]`,
  `attorneys[]{name, number, status, phone}`. (Attorney bar number is the `number` field.)
- **`financials`** (nullable) — `party`, `assessment`, `payments`, `balanceDue`, `asOf`,
  `transactions[]{date, description, amount}`.
- **`hearings[]`** — `dateTime`, `type`, `judge`, `location`, `result`.
- **`events[]`** (the Odyssey phase-ordered timeline) — `date`, `phase`, `event`, `description`,
  `party`, `files[]`.
- **`docket[]`** (the richer re:SearchTX view; combo only) — `date`, `event`, `type`, `comment`,
  `documents[]{name, pages, file}`.
- **`documents[]`** (filed PDFs) — `file`, `filename`, `title`, `declaredPageCount`, `docketEvent`,
  `filingDate`. (No `sha256` / `actualPageCount` here yet — those are exploder/DuckDB-side.)

## Who supplies what (`providers.py`, `unify.py`)

- **Odyssey (base):** identity, parties (role/name/representation/location/attorneys), the timeline
  `events`, `financials`, and `documents` (from `filings.json`).
- **re:SearchTX (combo merge):** attorney bar `number` (matched by name), party `aliases`,
  `caseCategory`, `clerk`, `lastRefreshed`, `hearings`, `docket`, `caseFlags`, `caseCrossReferences`.
- **Normalization:** dates → ISO (`unify.normalize_date`). Everything else passes through as-is —
  no status tokenization, no name reformatting, no title trimming. Every field records its source(s)
  in `sources` / `provenance`; missing standard fields are listed in `gaps`.

## DuckDB index (`db.py`, `SCHEMA_VERSION` 3)

A derived, regenerable index over the same record plus the exploded corpus. Tables: `cases`,
`parties`, `financials`, `financial_transactions`, `case_gaps`, `events`, `images`, `image_events`,
`documents`, `chunks` (one row per page; FTS over `text`), and the `knowledge_documents` stub. Read
`db.py` `_SCHEMA_STATEMENTS` for exact columns.

## Below the image (future — ROADMAP)

The image (a filed PDF) is the court-defined leaf. Decomposing it into documents-within and pages
with per-page text + image pointers, plus confidence scored against both sources, is the v0.4.0 work
in the [ROADMAP](../ROADMAP.md). It is additive and never alters the mirrored record above.
