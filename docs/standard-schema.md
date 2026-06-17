# The Standard Court-Record Schema (down to the image level)

> **What this is.** The *court* defines the record structure down to the **image** (a filed PDF).
> Lawnlord's job at this level is not to invent or interpret — it is to **mirror** that structure
> faithfully and normalize it into one standard shape. `txe` (re:SearchTX) and `ody` (Odyssey) are
> **two views of the same underlying court data**; their differences are field names, formats, and
> view taxonomies — not competing facts. This document is the unified standard those two views map
> into.
>
> **The boundary.** This schema stops at the **image**. The court system treats an image as an
> opaque **container of pages**. Everything below the image (documents-within, sections, analysis)
> is *additive* — lawnlord's own decomposition — and must not begin until this standard schema and
> the image→pages explosion are perfect.

## Hierarchy (court-defined)

```
Case
├── identity        (caseNumber, title, court, judge, type, status, dates, disposition, financials)
├── parties[]       (role, name, representation, attorneys[bar #])
└── filings[]       (docket submissions — date, event, type, party, comment)
    └── images[]    (filed PDFs — THE LEAF; an opaque container of pages to the court)
```

## Source-equivalence principle

The two portals render the same record. Where they differ:

| Difference kind | Example (case 25-09-14566) | Standard rule |
| --- | --- | --- |
| **Date format** | `09/05/2025` (ody) vs `9/5/2025` (txe) | Normalize to ISO `2025-09-05`; keep raw per source. |
| **Name format** | `O'Grady, John William` vs `John William O'Grady` | Canonical = `Last, First`; keep both as aliases. |
| **Venue facet** | `284th Judicial District Court` (court) vs `Montgomery County - District Clerk` (clerk) | Keep **both** — `court` and `clerk` are distinct fields, not a conflict. |
| **View taxonomy** | caseType `Foreclosure - Other Foreclosure` vs `Other Civil`/`Civil - Other Civil` | Keep the **most specific** as `caseType`; retain the other as `caseTypeAlt`. Not a conflict — two portals' categories for one case. |
| **Status wording** | `Disposed` vs `Closed (Disposed)` | Normalize to a canonical token; keep raw. |

Every standard field records which view(s) supplied it (`sources: [ody, txe]`) so the mirror stays
auditable — but the value is a single normalized truth, not a reconciliation of disagreement.

## Case identity

| Standard field | Type | ody source | txe source | Normalization |
| --- | --- | --- | --- | --- |
| `caseNumber` | str | `caseNumber` | `caseInformation.caseNumber` | identical |
| `title` | str | `caseTitle` | `caseInformation.caseTitle` | trim |
| `court` | str | `case-history.court` / `location` | — | as-is |
| `clerk` | str | — | `caseInformation.location` | as-is |
| `judicialOfficer` | str | `case-history.judicialOfficer` | `caseInformation.judge` | `Last, First` |
| `caseType` | str | `caseType` | `caseInformation.caseType` | most specific |
| `caseTypeAlt` | str | — | `caseInformation.caseCategory` | the other label |
| `status` | str | `status` | `caseInformation.caseStatus` | canonical token |
| `dateFiled` | date | `dateFiled` | `caseInformation.caseFiledDate` | ISO |
| `citationNumber` | str? | `case-summary.citationNumber` | — | null-safe |
| `sourceUrls` | str[] | `sourceUrl` | `_meta.caseUrl` | collect both |
| `lastRefreshed` | datetime | (`sources[]`) | `caseInformation.caseLastRefreshed` | freshness, per source |
| `caseFlags` | list | — | `caseFlags.rows` | as-is (empty here) |
| `crossReferences` | list | — | `caseCrossReferences.rows` | as-is (empty here) |

### Disposition (sub-object)

| Field | ody source | txe |
| --- | --- | --- |
| `type` | `case-history.disposition.type` | (derivable from status) |
| `date` | `disposition.date` | — |
| `comment` | `disposition.comment` ("Final Summary Judgment") | — |
| `judicialOfficer` | `disposition.judicialOfficer` | — |

### Financials (sub-object)

| Field | ody source | txe |
| --- | --- | --- |
| `totalAssessment` | `financialInformation.totalFinancialAssessment` | — |
| `totalPayments` | `financialInformation.totalPaymentsAndCredits` | — |
| `balanceDue` / `asOf` | `financialInformation.balanceDueAsOf.{amount,date}` | — |
| `transactions[]` | `register-of-actions.financialInformation.transactions[]` {date, description, amount} | — |

## Parties[]

| Standard field | ody source | txe source | Normalization |
| --- | --- | --- | --- |
| `role` | `parties[].role` | `parties.rows[].type` | identical |
| `name` | `parties[].name` | `parties.rows[].name` | `Last, First`; keep aliases |
| `aliases` | — | `parties.rows[].nicknameAlias` | collect |
| `representation` | `register.parties[].representation` ("Pro Se") | — | as-is |
| `location` | `register.parties[].location` | — | as-is |
| `attorneys[].name` | `parties[].attorneys[].name` | `parties.rows[].attorneys[].name` | match by name |
| `attorneys[].barNumber` | — | `attorneys[].attorneyNumber` | from txe |
| `attorneys[].status` | `attorneys[].status` ("Retained") | — | as-is |
| `attorneys[].phone` | `attorneys[].phone` | — | as-is |

## Filings[] (docket submissions)

A filing is a docket event/submission; it contains **one or more images**.

| Standard field | ody source | txe source | Normalization |
| --- | --- | --- | --- |
| `date` | `timeline[].date` / `register.otherEventsAndHearings[].date` | `events.rows[].date` | ISO |
| `event` | `timeline[].event` | `events.rows[].event` | as-is |
| `type` | — | `events.rows[].type` | as-is |
| `phase` | `timeline[].phase` (ody-only narrative grouping) | — | keep (ody enrichment) |
| `party` | `timeline[].party` | — | as-is |
| `comment` | — | `events.rows[].comments` (judge/registrar note) | as-is |
| `description` | `timeline[].description` | — | as-is |
| `images[]` | `timeline[].files[]` | `events.rows[].documents[]` | union by image |

> **Event-set note.** ody `timeline` = 20 (phase-tagged); register `otherEventsAndHearings` and txe
> `events` = 26 (txe states: "paginated 20/page, total 26"). The standard filing list is the
> **union** — same docket, one view simply paginated. Hearings (txe `hearings.rows`) are filings of
> type *Hearing* (e.g. the canceled Bench Trial), merged into the same list.

## Images[] (the leaf — a container of pages)

The filed PDF. Odyssey's own field name for it is `image`.

| Standard field | ody source | txe source | Normalization |
| --- | --- | --- | --- |
| `title` | `filings.json …[].image` | `events.rows[].documents[].name` | trim |
| `file` | `filings.json …[].file` | (linked by name) | intake-relative path |
| `declaredPageCount` | `filings.json …[].pageCount` | `documents[].pages` | int; cross-check vs actual |
| `filingDate` | `filings.json …[].date` | — | ISO |
| `docketEvent` | `filings.json …[].event` | — | as-is |
| `sha256` | (computed from bytes) | — | content hash — the preservation key |
| `actualPageCount` | (computed by exploder) | — | cross-checked vs declared |

**Below this line is not court-defined.** The image is a container of pages; image→pages explosion
(every page extracted, fully searchable, losslessly reassemblable) is the next must-perfect step.
Breaking an image into documents-within (Motion, Exhibit A, …) is *additive* and comes after.

## Status of this standard

The down-to-image mirror shipped in **v0.3.0**: field-complete mirror-view readers (nothing dropped,
[#17](https://github.com/jwogrady/lawnlord/issues/17)) feed a mirror-unifier into canonical
`case.json` v2.0 ([#18](https://github.com/jwogrady/lawnlord/issues/18)), source-tagged and
normalized — mirror-unification, not conflict-reconciliation. The decisions still open *below* the
image line — whether `section` returns as a first-class level, and the single `document` glossary —
are tracked in [#34](https://github.com/jwogrady/lawnlord/issues/34) /
[#35](https://github.com/jwogrady/lawnlord/issues/35) (v0.4.0). See [CHANGELOG](../CHANGELOG.md) for
what shipped and [ROADMAP](ROADMAP.md) for what's next.
