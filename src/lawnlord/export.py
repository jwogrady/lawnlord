"""Read the case views out of a case's DuckDB mirror.

Two lenses, both read-only — one query set → a JSON-able dict the viewer
consumes, never by re-parsing the zip:

- The **Actual lens** (:func:`export_actual`) reproduces the Odyssey portal from
  the **mirror** (the seven tables :mod:`lawnlord.ingest` populates): case header,
  parties, the register of actions with each entry's filed documents, and the
  document set. It ends at the image, like Odyssey.
- The **Exploded lens** (:func:`export_exploded`) goes inside each PDF:
  case → image → document → page, each page carrying *every* transcription
  variation beside it.

The Exploded lens is **addressable at every hierarchy level** (ADR-0007) — the
whole case, or a single filing, image, document, or page — each a pure function
of the connection returning the same nested shape scoped to that node. A
**filing** is a grouping, not a tree node: filings↔images are many-to-many via
``image_events``, so a filing-level export returns the images linked to that
event (overlap with other filings allowed). This module never writes.
"""

from __future__ import annotations

import difflib

import duckdb

# --- Divergence & agreement (ADR-0008) --------------------------------------
#
# Confidence needs the spread between readings *shown* (the text viewer) and
# *quantified* (the gauges). Define it once, here, so every consumer agrees.
#
# A page's transcriptions are compared against a single **canonical anchor**:
#   - the ``pdf_text`` reading when the page has one (the court's own text
#     layer is ground truth); otherwise
#   - the cross-model **consensus** of the ``ai`` readings, defined as the
#     *medoid* — the variation whose mean pairwise similarity to the others is
#     highest (ties broken by model name ascending). A lone ``ai`` reading is
#     trivially its own anchor.
#
# Each variation then carries:
#   - ``agreement``: a normalized 0.0–1.0 similarity to the anchor, the
#     ``difflib.SequenceMatcher`` ratio over whitespace-split *token* lists,
#     rounded to AGREEMENT_PRECISION. The anchor scores 1.0.
#   - ``divergence``: a JSON-serializable list of the changed spans
#     (``replace``/``delete``/``insert`` opcodes) between the anchor's tokens
#     and the variation's tokens, each carrying the op kind, the anchor-side and
#     variation-side token index ranges, and the literal token substrings — so a
#     viewer can highlight without re-diffing. The anchor's divergence is empty.
#
# Everything is computed from text alone: deterministic given fixed input.

AGREEMENT_PRECISION = 4
# A page is flagged for review (a worklist entry) when any reading drifts too
# far from the anchor, any reading's model self-assessed fidelity is too low, or
# an expected variation is missing for that page.
AGREEMENT_FLAG_THRESHOLD = 0.8
FIDELITY_FLAG_THRESHOLD = 0.8


def _tokens(text: str | None) -> list[str]:
    """Whitespace-split tokens — the unit of comparison for agreement and
    divergence. ``None`` text (an absent reading) is the empty token list."""
    return (text or "").split()


def agreement_score(anchor_text: str | None, text: str | None) -> float:
    """Normalized 0.0–1.0 similarity of ``text`` to ``anchor_text`` — the
    ``SequenceMatcher`` ratio over whitespace-split tokens, rounded. Two empty
    readings agree perfectly (1.0)."""
    a, b = _tokens(anchor_text), _tokens(text)
    if not a and not b:
        return 1.0
    ratio = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    return round(ratio, AGREEMENT_PRECISION)


def divergence_spans(anchor_text: str | None, text: str | None) -> list[dict]:
    """The changed token spans between the anchor and a variation, as a
    JSON-serializable list. Each span carries the opcode kind plus the
    anchor-side (``a``) and variation-side (``b``) token index ranges and the
    literal token substrings, so a later viewer can highlight without re-diffing.
    Equal runs are omitted; identical text yields ``[]``."""
    a, b = _tokens(anchor_text), _tokens(text)
    spans: list[dict] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, a, b, autojunk=False
    ).get_opcodes():
        if op == "equal":
            continue
        spans.append(
            {
                "op": op,
                "anchor": {"start": i1, "end": i2, "tokens": a[i1:i2]},
                "variation": {"start": j1, "end": j2, "tokens": b[j1:j2]},
            }
        )
    return spans


def _consensus_index(texts: list[str | None]) -> int:
    """Index of the medoid of ``texts`` — the reading whose mean pairwise
    agreement to the others is highest. Callers pass an already model-name-sorted
    list so ``max`` keeps the first (lowest model name) on a tie. A single
    element is trivially its own consensus."""
    if len(texts) == 1:
        return 0
    best_idx, best_mean = 0, -1.0
    for i, ti in enumerate(texts):
        others = [agreement_score(ti, tj) for j, tj in enumerate(texts) if j != i]
        mean = sum(others) / len(others)
        if mean > best_mean:
            best_idx, best_mean = i, mean
    return best_idx


def _anchor_index(variations: list[dict]) -> int | None:
    """Index of the canonical anchor within ``variations`` (already sorted
    ground-truth-first then ``ai`` by model). The ``pdf_text`` reading if present,
    else the consensus medoid of the ``ai`` readings. ``None`` for an empty list."""
    if not variations:
        return None
    for i, v in enumerate(variations):
        if v["source"] == "pdf_text":
            return i
    return _consensus_index([v["text"] for v in variations])


def _annotate_divergence(variations: list[dict]) -> list[dict]:
    """Add ``agreement``, ``divergence`` and ``flagged`` to each variation in
    place against the page's canonical anchor. The anchor gets ``agreement: 1.0``,
    an empty ``divergence`` and ``flagged: False``. ``flagged`` is the per-reading
    review signal — ``True`` when a non-anchor reading drifts below
    :data:`AGREEMENT_FLAG_THRESHOLD` or its self-assessed ``fidelity`` is below
    :data:`FIDELITY_FLAG_THRESHOLD` — decided here (the same thresholds
    :func:`_rollup` uses) so the viewer renders the flag without re-scoring.
    Returns the same list for convenience."""
    anchor_idx = _anchor_index(variations)
    if anchor_idx is None:
        return variations
    anchor_text = variations[anchor_idx]["text"]
    for i, v in enumerate(variations):
        if i == anchor_idx:
            v["agreement"] = 1.0
            v["divergence"] = []
            v["flagged"] = False
        else:
            v["agreement"] = agreement_score(anchor_text, v["text"])
            v["divergence"] = divergence_spans(anchor_text, v["text"])
            fid = v.get("fidelity")
            v["flagged"] = v["agreement"] < AGREEMENT_FLAG_THRESHOLD or (
                fid is not None and fid < FIDELITY_FLAG_THRESHOLD
            )
    return variations


def _one(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> dict:
    cur = con.execute(sql, params or [])
    row = cur.fetchone()
    if row is None:
        return {}
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def export_actual(con: duckdb.DuckDBPyConnection) -> dict:
    """Build the Actual-lens payload from the mirror tables (read-only)."""
    case = _one(
        con,
        "SELECT id AS number, title, court, case_type AS caseType, status, "
        "date_filed AS dateFiled, judicial_officer AS judicialOfficer "
        "FROM cases LIMIT 1",
    )

    parties = _rows(
        con,
        "SELECT role, name, representation, location FROM parties "
        "ORDER BY role, name",
    )

    documents = _rows(
        con,
        "SELECT title, filename, intake_path AS intakePath, "
        "declared_page_count AS declaredPageCount, filing_date AS filingDate, "
        "docket_type AS docketEvent FROM images ORDER BY filing_date, title",
    )

    # The register of actions: every event, in docket order, with the filed
    # documents (images) linked to it via image_events.
    events = _rows(
        con,
        "SELECT id, date, event_type AS event, party, phase AS section "
        "FROM events ORDER BY date, id",
    )
    docs_for: dict[str, list[dict]] = {}
    for link in _rows(
        con,
        "SELECT ie.event_id AS event_id, i.title, i.filename, "
        "i.intake_path AS intakePath, i.declared_page_count AS declaredPageCount "
        "FROM image_events ie JOIN images i ON i.id = ie.image_id",
    ):
        docs_for.setdefault(link.pop("event_id"), []).append(link)
    register = []
    for e in events:
        eid = e.pop("id")
        e["documents"] = docs_for.get(eid, [])
        register.append(e)

    return {
        "case": case,
        "parties": parties,
        "registerOfActions": register,
        "documents": documents,
    }


# --- Exploded lens: case → image → document → page → transcriptions ---------
#
# A page's transcriptions are *every current variation* — the latest rev per
# (page_id, source, model). pdf_text has a null model, so match nulls with
# IS NOT DISTINCT FROM. Ordered ground-truth first (pdf_text), then ai by model.

_VARIATIONS_SQL = """
SELECT pt.page_id, pt.source, pt.model, pt.rev, pt.fidelity, pt.text,
       pt.created_at AS createdAt
FROM page_text pt
JOIN (SELECT page_id, source, model, max(rev) AS rev FROM page_text
      GROUP BY page_id, source, model) m
ON m.page_id = pt.page_id AND m.source = pt.source
 AND m.model IS NOT DISTINCT FROM pt.model AND m.rev = pt.rev
"""


def _variations_by_page(
    con: duckdb.DuckDBPyConnection, where: str = "", params: list | None = None
) -> dict[str, list[dict]]:
    """Map page_id → its current transcription variations (latest rev per
    ``(page_id, source, model)``), each sorted ground-truth-first."""
    sql = _VARIATIONS_SQL
    if where:
        sql += f" AND pt.page_id IN ({where})"
    by_page: dict[str, list[dict]] = {}
    for r in _rows(con, sql, params):
        entry = {
            "source": r["source"],
            "model": r["model"],
            "rev": r["rev"],
            "createdAt": r["createdAt"],
            "fidelity": r["fidelity"],
            "text": r["text"],
        }
        by_page.setdefault(r["page_id"], []).append(entry)
    for entries in by_page.values():
        entries.sort(key=lambda t: (t["source"] != "pdf_text", t["source"], t["model"] or ""))
        _annotate_divergence(entries)
    return by_page


def _pages(
    con: duckdb.DuckDBPyConnection, where: str = "", params: list | None = None
) -> list[dict]:
    """Pages (optionally scoped by a WHERE clause), each with its
    ``transcriptions`` list."""
    sql = (
        "SELECT id, document_id, page_number AS pageNumber, "
        "page_image_path AS png FROM pages"
    )
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY document_id, page_number"
    rows = _rows(con, sql, params)
    if not rows:
        return []
    page_ids = [r["id"] for r in rows]
    placeholders = ", ".join("?" for _ in page_ids)
    vars_by_page = _variations_by_page(con, placeholders, page_ids)
    for p in rows:
        p["transcriptions"] = vars_by_page.get(p["id"], [])
    return rows


def export_page(con: duckdb.DuckDBPyConnection, page_id: str) -> dict:
    """A single page scoped to ``page_id``, with its ``transcriptions`` list."""
    pages = _pages(con, "id = ?", [page_id])
    if not pages:
        return {}
    page = pages[0]
    page.pop("document_id", None)
    return {"page": page}


def export_regions(con: duckdb.DuckDBPyConnection, *, page_id: str) -> dict:
    """The spatial-anchor regions for a page (ADR-0009), read-only — the geometry
    the on-image highlight renderer (#129) overlays. Each region is a normalized
    ``0..1`` top-left box ``(x0, y0, x1, y1)`` anchored to a source row via
    ``(anchorKind, anchorId)`` and covering the anchor text's
    ``[charStart, charEnd)`` token, ordered by anchor then span. An empty list
    when a page has no captured geometry — the renderer falls back to text-only."""
    regions = _rows(
        con,
        "SELECT id, anchor_id AS anchorId, anchor_kind AS anchorKind, "
        "span_index AS spanIndex, char_start AS charStart, char_end AS charEnd, "
        "x0, y0, x1, y1, origin, confidence FROM page_regions "
        "WHERE page_id = ? ORDER BY anchor_id, span_index",
        [page_id],
    )
    return {"pageId": page_id, "regions": regions}


def _documents_for(
    con: duckdb.DuckDBPyConnection, where: str = "", params: list | None = None
) -> list[dict]:
    """Documents (optionally scoped) with their pages + transcriptions nested."""
    sql = (
        "SELECT id, image_id, title, page_count AS pageCount FROM documents"
    )
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY image_id, id"
    docs = _rows(con, sql, params)
    if not docs:
        return []
    doc_ids = [d["id"] for d in docs]
    placeholders = ", ".join("?" for _ in doc_ids)
    pages_by_doc: dict[str, list[dict]] = {}
    for p in _pages(con, f"document_id IN ({placeholders})", doc_ids):
        pages_by_doc.setdefault(p.pop("document_id"), []).append(p)
    for d in docs:
        d["pages"] = pages_by_doc.get(d["id"], [])
    return docs


def export_document(con: duckdb.DuckDBPyConnection, document_id: str) -> dict:
    """A single document scoped to ``document_id``, with its pages nested."""
    docs = _documents_for(con, "id = ?", [document_id])
    if not docs:
        return {}
    doc = docs[0]
    doc.pop("image_id", None)
    return {"document": doc}


def _filings_by_image(
    con: duckdb.DuckDBPyConnection, image_ids: list[str]
) -> dict[str, list[dict]]:
    """Map image_id → the filings (events) that filed it, via ``image_events``
    (many-to-many: an image may appear under several filings). Each filing is
    ``{id, date, event, section}``, in docket order — read-only mirror data so
    the viewer can group case → filing → image without re-deriving anything."""
    if not image_ids:
        return {}
    placeholders = ", ".join("?" for _ in image_ids)
    by_image: dict[str, list[dict]] = {}
    for r in _rows(
        con,
        "SELECT ie.image_id AS image_id, e.id AS id, e.date AS date, "
        "e.event_type AS event, e.phase AS section "
        "FROM image_events ie JOIN events e ON e.id = ie.event_id "
        f"WHERE ie.image_id IN ({placeholders}) ORDER BY e.date, e.id",
        image_ids,
    ):
        by_image.setdefault(r.pop("image_id"), []).append(r)
    return by_image


def _images_for(
    con: duckdb.DuckDBPyConnection, where: str = "", params: list | None = None
) -> list[dict]:
    """Images (optionally scoped) with their filings + documents → pages nested."""
    sql = "SELECT id AS imageId, title, filename FROM images"
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY filing_date, title"
    images = _rows(con, sql, params)
    if not images:
        return []
    image_ids = [img["imageId"] for img in images]
    placeholders = ", ".join("?" for _ in image_ids)
    docs_by_image: dict[str, list[dict]] = {}
    for d in _documents_for(con, f"image_id IN ({placeholders})", image_ids):
        docs_by_image.setdefault(d.pop("image_id"), []).append(d)
    filings_by_image = _filings_by_image(con, image_ids)
    for img in images:
        img["filings"] = filings_by_image.get(img["imageId"], [])
        img["documents"] = docs_by_image.get(img["imageId"], [])
    return images


def export_image(con: duckdb.DuckDBPyConnection, image_id: str) -> dict:
    """A single image scoped to ``image_id``, with its documents → pages nested."""
    images = _images_for(con, "id = ?", [image_id])
    if not images:
        return {}
    return {"image": images[0]}


def export_filing(con: duckdb.DuckDBPyConnection, filing_id: str) -> dict:
    """A filing-level export: the images linked to event ``filing_id`` via
    ``image_events`` (a many-to-many grouping — overlap with other filings is
    allowed), each image fully exploded. Returns the event header alongside its
    images."""
    event = _one(
        con,
        "SELECT id, date, event_type AS event, party, phase AS section "
        "FROM events WHERE id = ?",
        [filing_id],
    )
    if not event:
        return {}
    image_ids = [
        r["image_id"]
        for r in _rows(
            con,
            "SELECT image_id FROM image_events WHERE event_id = ?",
            [filing_id],
        )
    ]
    if image_ids:
        placeholders = ", ".join("?" for _ in image_ids)
        images = _images_for(con, f"id IN ({placeholders})", image_ids)
    else:
        images = []
    return {"filing": event, "images": images}


def export_exploded(
    con: duckdb.DuckDBPyConnection,
    *,
    image_id: str | None = None,
    document_id: str | None = None,
    page_id: str | None = None,
    filing_id: str | None = None,
) -> dict:
    """Build the Exploded-lens payload (read-only): case → image → document →
    page, each page carrying *every* current transcription variation beside it
    in a ``transcriptions`` list.

    With no selector this is the whole-case export ``{"images": [...]}``. Each
    image carries a ``filings`` list (the events that filed it, via
    ``image_events``) so the viewer can group case → filing → image from one
    read-only fetch. Pass a selector to scope to one node:

    - ``page_id`` → :func:`export_page`
    - ``document_id`` → :func:`export_document`
    - ``image_id`` → :func:`export_image`
    - ``filing_id`` → :func:`export_filing` (the event's linked images)

    Each page's ``transcriptions`` is the **latest rev per
    ``(page_id, source, model)``**, ordered ground-truth first (``pdf_text``)
    then ``ai`` by model name; each entry carries ``source``, ``model``, ``rev``,
    ``createdAt``, ``fidelity``, ``text``, plus an ``agreement`` (0.0–1.0
    similarity to the page's canonical anchor), a ``divergence`` (the changed
    token spans against that anchor) and a ``flagged`` review signal — see
    :func:`_annotate_divergence`. An untranscribed page carries an empty list.
    The lens always shows the page image regardless.
    """
    if page_id is not None:
        return export_page(con, page_id)
    if document_id is not None:
        return export_document(con, document_id)
    if image_id is not None:
        return export_image(con, image_id)
    if filing_id is not None:
        return export_filing(con, filing_id)
    return {"images": _images_for(con)}


# --- Aggregate metrics (ADR-0008) -------------------------------------------


def _page_rows_for_metrics(
    con: duckdb.DuckDBPyConnection, image_id: str | None
) -> list[dict]:
    """The pages in scope (whole case, or one image), each with its annotated
    ``transcriptions`` list — the same shape the exploded lens emits, reused so
    metrics and the viewer can never disagree on agreement/divergence."""
    if image_id is None:
        pages = _pages(con)
    else:
        pages = _pages(con, "image_id = ?", [image_id])
    return pages


def _rollup(pages: list[dict]) -> dict:
    """Aggregate one scope (case or a single image) from its annotated pages.

    - **coverage**: fraction of expected ``(page × variation)`` cells present,
      where the expected variation set is the union of ``(source, model)`` keys
      seen across the scope. A page missing a model others have lowers coverage.
      Raw ``present``/``expected`` counts are surfaced alongside the fraction.
    - **meanAgreement**: mean ``agreement`` over the *non-anchor* variations
      (the anchor's trivial 1.0 is excluded so the number reflects real spread).
    - **fidelityByModel**: per model, ``count`` and ``min``/``mean``/``max`` of
      the recorded fidelities (fidelities of ``None`` — e.g. ``pdf_text`` — are
      ignored).
    - **flaggedPages**: page ids flagged for review — any reading below
      :data:`AGREEMENT_FLAG_THRESHOLD`, any fidelity below
      :data:`FIDELITY_FLAG_THRESHOLD`, or an expected variation missing.
    - **flaggedPageDetails**: the same flagged pages, each with the sorted
      ``reasons`` that fired (``"divergent"`` / ``"low_fidelity"`` /
      ``"missing"``) so a worklist can categorize a page without re-deciding it.
    """
    # Expected variation set = union of (source, model) keys across the scope.
    expected_keys: set[tuple[str, str | None]] = set()
    for p in pages:
        for v in p["transcriptions"]:
            expected_keys.add((v["source"], v["model"]))

    present = sum(len(p["transcriptions"]) for p in pages)
    expected = len(pages) * len(expected_keys)
    coverage = round(present / expected, AGREEMENT_PRECISION) if expected else 1.0

    agreements: list[float] = []
    fidelities_by_model: dict[str, list[float]] = {}
    flagged: list[str] = []
    flagged_details: list[dict] = []
    for p in pages:
        keys = {(v["source"], v["model"]) for v in p["transcriptions"]}
        # The flag reasons that fired for this page, so a worklist can say *why*
        # without re-deciding it (the viewer never re-applies the thresholds).
        reasons: set[str] = set()
        if expected_keys - keys:  # missing an expected variation
            reasons.add("missing")
        for v in p["transcriptions"]:
            label = v["model"] or v["source"]
            fid = v.get("fidelity")
            if fid is not None:
                fidelities_by_model.setdefault(label, []).append(fid)
                if fid < FIDELITY_FLAG_THRESHOLD:
                    reasons.add("low_fidelity")
        # Mean agreement is over the *non-anchor* readings: every variation
        # except the page's anchor (the same anchor _annotate_divergence used).
        anchor_idx = _anchor_index(p["transcriptions"])
        for i, v in enumerate(p["transcriptions"]):
            if i == anchor_idx:
                continue
            agreements.append(v["agreement"])
            if v["agreement"] < AGREEMENT_FLAG_THRESHOLD:
                reasons.add("divergent")
        if reasons:
            flagged.append(p["id"])
            flagged_details.append({"pageId": p["id"], "reasons": sorted(reasons)})

    mean_agreement = (
        round(sum(agreements) / len(agreements), AGREEMENT_PRECISION)
        if agreements
        else 1.0
    )
    fidelity_distribution = {
        model: {
            "count": len(vals),
            "min": round(min(vals), AGREEMENT_PRECISION),
            "mean": round(sum(vals) / len(vals), AGREEMENT_PRECISION),
            "max": round(max(vals), AGREEMENT_PRECISION),
        }
        for model, vals in sorted(fidelities_by_model.items())
    }
    return {
        "pages": len(pages),
        "coverage": {
            "fraction": coverage,
            "present": present,
            "expected": expected,
            "expectedVariations": [
                {"source": s, "model": m}
                for s, m in sorted(expected_keys, key=lambda k: (k[0], k[1] or ""))
            ],
        },
        "meanAgreement": mean_agreement,
        "fidelityByModel": fidelity_distribution,
        "flaggedPageCount": len(flagged),
        "flaggedPages": flagged,
        "flaggedPageDetails": flagged_details,
    }


def export_metrics(
    con: duckdb.DuckDBPyConnection, *, image_id: str | None = None
) -> dict:
    """Aggregate divergence/confidence metrics rolled up at the **case** and
    **image** levels (ADR-0008). Read-only and deterministic given fixed text.

    Returns ``{"case": <rollup>, "images": [{"imageId", ...<rollup>}, ...]}``.
    Each rollup is :func:`_rollup` over the annotated pages in that scope:
    coverage, mean (non-anchor) agreement, a per-model fidelity distribution, and
    the flagged-page worklist. With ``image_id`` set, the case rollup is scoped to
    that image and ``images`` holds just that one image.
    """
    if image_id is not None:
        image_ids = [image_id]
    else:
        image_ids = [
            r["id"] for r in _rows(con, "SELECT id FROM images ORDER BY filing_date, title")
        ]

    per_image = []
    all_pages: list[dict] = []
    for iid in image_ids:
        pages = _page_rows_for_metrics(con, iid)
        all_pages.extend(pages)
        per_image.append({"imageId": iid, **_rollup(pages)})

    return {"case": _rollup(all_pages), "images": per_image}
