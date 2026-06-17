# The standard court-record schema (developer code summary)

> **Provable from the code.** Every field below is what `canonical.to_canonical()` (`canonical.py`)
> actually produces and what `db.py` actually creates. If this doc and the code disagree, **the code
> wins.** Below-the-image decomposition and analysis are future work — see the
> [ROADMAP](../ROADMAP.md).

Lawnlord mirrors the court record from the Odyssey (`ody`) and re:SearchTX (`txe`) portals into one
canonical `case.json`. The two portals are two views of the same record; lawnlord normalizes them
into one shape and tags which source supplied each field.

## Vocabulary

One word — *document* — means different things in different layers; this glossary is canonical, and
each layer maps to it. (Issue #35.)

| Canonical term | Meaning | `case.json` (`canonical.py`) | DuckDB index (`db.py`) | on-disk corpus (`corpus.py`) |
|---|---|---|---|---|
| **case** | the lawsuit | `case` | `cases` | `archive` |
| **event** | a docket entry / filing | `events`, `docket` | `events` | — |
| **image** | a **filed PDF** (the court's leaf) | `documents[]` ⚠️ | `images` | `submissions/<…>/documents/<…>` |
| **document** | a logical document *within* an image (Motion, Exhibit A, Affidavit) — `section == document` (#34) | — *(not serialized)* | `documents` | `sections/<…>` |
| **page** | a page of a document | — | `chunks` (one row per page) | `pages/`, `text/` |

⚠️ **The collision.** `case.json`'s `documents[]` are the **filed PDFs** — *images* in the index
vocabulary — **not** the index's `documents` (the logical documents *within* an image). When reading
`case.json`, treat `documents[]` as images. Renaming `case.json`'s `documents[]` → `images[]` to remove
the collision outright is a deferred schema change; until then, this mapping is the contract.

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

## Below the image: the `document` level — `section == document` (decision, #34)

The image is the court-defined leaf. lawnlord decomposes it into the **documents within an image** —
the logical filings the exploder detects from bookmarks/headings (a Motion, Exhibit A, an Affidavit).
This is **one** boundary level, not two: the exploder's on-disk vocabulary calls these boundaries
"sections," but they are the same thing as the index's `documents`. **`section == document`** — there
is no separate first-class `section` level, because the data has no sub-document level to model.

- The DuckDB index stores them in `documents` (there is no `sections` table); `chunks` link to
  `document_id`.
- The on-disk corpus keeps its `sections/` grouping as an implementation detail, mapped to a
  `documents` row at the index boundary (`index.py`).
- **Junk bookmarks are excluded** from the document set: embedded-file/remote targets (page `< 1`),
  non-top-level (level ≠ 1) entries, and — for the reassembled outline — filename-like or
  bare-numeric titles (`boundaries.py`, `assemble._is_junk_bookmark`).

Reviving `section` as its own level is deferred unless a real sub-document structure appears; today it
would be an empty level.

The remaining below-the-image work — per-page text + preserved-image pointers and confidence scored
against both sources — is the rest of the v0.4.0 chain in the [ROADMAP](../ROADMAP.md). It is additive
and never alters the mirrored record above.
