"""Steps 1-2 of the resolution funnel: internal catalog fuzzy matching.

The catalog is the firm's own (imperfect, sometimes stale) record of known
vendors/parents. Matching against it is pure data lookup -- no LLM call --
so it's tried first as the cheapest, fastest signal.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from .normalize import abbreviate, fuzzy_score

MATCH_THRESHOLD = 95.0
TIE_MARGIN = 3.0  # if the top two candidates are within this many points, treat as a tie
STALENESS_THRESHOLD_MONTHS = 18

# Fixed so the committed example run in /results is reproducible on any machine,
# any day. A production deployment would use the real current date.
REFERENCE_DATE = dt.date(2025, 1, 1)


@dataclass
class CatalogRow:
    catalog_name: str
    parent_company: str
    domain: str
    address: str
    last_verified: dt.date


def load_catalog(path: Path) -> list[CatalogRow]:
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            rows.append(
                CatalogRow(
                    catalog_name=r["catalog_name"],
                    parent_company=r["parent_company"],
                    domain=r["domain"],
                    address=r["address"],
                    last_verified=dt.date.fromisoformat(r["last_verified"]),
                )
            )
    return rows


def _is_stale(last_verified: dt.date) -> bool:
    months = (REFERENCE_DATE.year - last_verified.year) * 12 + (
        REFERENCE_DATE.month - last_verified.month
    )
    return months >= STALENESS_THRESHOLD_MONTHS


@dataclass
class CatalogMatchResult:
    resolved: bool
    query_used: str  # "as_is" | "abbreviation"
    query_string: str
    top_matches: list[tuple[CatalogRow, float]]
    tied: bool
    stale: bool


def match(vendor_name: str, catalog: list[CatalogRow]) -> CatalogMatchResult | None:
    """Try catalog match as-is, then by abbreviation. Returns None if neither finds
    a confident (>=95%) top match."""
    for query_used, query_string in (
        ("as_is", vendor_name),
        ("abbreviation", abbreviate(vendor_name)),
    ):
        scored = sorted(
            ((row, fuzzy_score(query_string, row.catalog_name)) for row in catalog),
            key=lambda t: t[1],
            reverse=True,
        )
        top = scored[:3]
        if not top or top[0][1] < MATCH_THRESHOLD:
            continue
        tied = len(top) > 1 and (top[0][1] - top[1][1]) <= TIE_MARGIN and top[1][1] >= MATCH_THRESHOLD
        stale = _is_stale(top[0][0].last_verified)
        return CatalogMatchResult(
            resolved=True,
            query_used=query_used,
            query_string=query_string,
            top_matches=top,
            tied=tied,
            stale=stale,
        )
    return None
