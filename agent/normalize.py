"""Name normalization and fuzzy matching helpers.

Deliberately dependency-free (stdlib difflib) so the POC runs with zero
install friction. The real system used a similar normalize-then-fuzzy-match
approach as the first, cheapest step before any LLM call.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Legal-entity suffixes stripped before comparing names. Order matters:
# longer/more specific phrases first so they match before their substrings do.
LEGAL_SUFFIXES = [
    "private limited",
    "pte ltd",
    "pte. ltd.",
    "gmbh & co kg",
    "gmbh",
    "s.a.r.l.",
    "s.a.",
    "s.p.a.",
    "b.v.",
    "n.v.",
    "co., ltd.",
    "co ltd",
    "corporation",
    "incorporated",
    "pty ltd",
    "pty",
    "ltd",
    "llc",
    "kk",
    "ag",
    "bv",
    "kg",
    "inc",
    "corp",
    "co",
]

_PAREN_RE = re.compile(r"\([^)]*\)")
_PUNCT_RE = re.compile(r"[^\w\s&]")
_WS_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Lowercase, drop parenthetical qualifiers/punctuation, strip legal suffixes."""
    n = name.lower()
    n = _PAREN_RE.sub(" ", n)
    n = _PUNCT_RE.sub(" ", n)
    n = _WS_RE.sub(" ", n).strip()

    changed = True
    while changed:
        changed = False
        for suffix in LEGAL_SUFFIXES:
            if n.endswith(" " + suffix):
                n = n[: -(len(suffix) + 1)].strip()
                changed = True
            elif n == suffix:
                n = ""
                changed = True
    return n


def abbreviate(name: str) -> str:
    """Build a likely abbreviation from a normalized name's significant words.

    "Northstar Analytics International Ltd" -> normalize -> "northstar
    analytics international" -> abbreviation "NAI". This mirrors the retry
    step the real agent takes when the spelled-out name doesn't fuzzy-match
    the catalog but a common abbreviation would.
    """
    normalized = normalize_name(name)
    words = [w for w in normalized.split() if w != "&"]
    if len(words) < 2:
        return name.upper()
    return "".join(w[0] for w in words).upper()


def fuzzy_score(a: str, b: str) -> float:
    """Similarity score in [0, 100] between two names, suffix/case/punct-insensitive."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 100.0
    return round(SequenceMatcher(None, na, nb).ratio() * 100, 1)
