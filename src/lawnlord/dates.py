"""Extract date-bearing facts from page text (#36).

A date here is a **fact** — "this date appears on this page, in this character
span" — not an interpretation. Whether a date is a deadline you must act on is
later, human-gated analysis (the "why" layer); it is never decided here, and
every extracted date is flagged ``needsReview`` by the indexer. These facts feed
the factual timeline (#30).

Three formats are recognised: ISO ``YYYY-MM-DD``, numeric ``M/D/Y`` (or ``M-D-Y``),
and long-form ``Month D, YYYY`` — the shapes courts use for filing dates, hearing
dates, and order/deadline dates.
"""

from __future__ import annotations

import re

from .unify import normalize_date

_MONTHS = {
    name: i
    for i, name in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}

_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMERIC = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
_LONG = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.IGNORECASE
)

_SNIPPET_RADIUS = 40


def _snippet(text: str, start: int, end: int) -> str:
    lo = max(0, start - _SNIPPET_RADIUS)
    hi = min(len(text), end + _SNIPPET_RADIUS)
    return " ".join(text[lo:hi].split())


def extract_dates(text: str) -> list[dict]:
    """Date facts found in ``text``, in order of appearance, de-duplicated by
    start offset.

    Each fact carries ``date`` (ISO when parseable, else the raw match), ``raw``,
    ``snippet`` (surrounding text), ``spanStart``/``spanEnd`` (character offsets),
    and a ``confidence`` (ISO highest, long-form lowest). No interpretation — the
    caller flags every fact for human review.
    """
    text = text or ""
    found: dict[int, dict] = {}

    def add(match: re.Match, iso: str, confidence: float) -> None:
        if match.start() in found:
            return
        found[match.start()] = {
            "date": iso,
            "raw": match.group(0),
            "snippet": _snippet(text, match.start(), match.end()),
            "spanStart": match.start(),
            "spanEnd": match.end(),
            "confidence": confidence,
        }

    for m in _ISO.finditer(text):
        add(m, m.group(0), 1.0)
    for m in _NUMERIC.finditer(text):
        add(m, normalize_date(m.group(0)), 0.9)
    for m in _LONG.finditer(text):
        month = _MONTHS[m.group(1).lower()]
        add(m, f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(2)):02d}", 0.85)

    return [found[start] for start in sorted(found)]
