"""Verified Resolution Cache.

Every resolution the LLM-as-judge grades PASS gets written here, keyed by
the parent's domain rather than any single name string. A vendor whose name
fuzzy-matches an already-verified alias resolves instantly from the cache --
no catalog lookup, no LLM call -- which is what makes the pipeline get
cheaper and faster the more it runs, instead of repeating full-cost
resolution on records it has effectively already seen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .normalize import fuzzy_score

CACHE_HIT_THRESHOLD = 90.0


@dataclass
class CacheEntry:
    domain: str
    parent_company: str
    aliases: list[str]
    confidence: float
    verified_epoch: int
    verified_by: str = "human_review"


@dataclass
class VerifiedResolutionCache:
    entries: list[CacheEntry] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "VerifiedResolutionCache":
        data = json.loads(path.read_text())
        entries = [
            CacheEntry(
                domain=e["domain"],
                parent_company=e["parent_company"],
                aliases=list(e["aliases"]),
                confidence=e["confidence"],
                verified_epoch=e["verified_epoch"],
                verified_by=e.get("verified_by", "human_review"),
            )
            for e in data.get("entries", [])
        ]
        return cls(entries=entries)

    def lookup(self, vendor_name: str) -> tuple[CacheEntry, float, str] | None:
        """Return (entry, score, matched_alias) for the best alias match above threshold, else None."""
        best: tuple[CacheEntry, float, str] | None = None
        for entry in self.entries:
            for alias in entry.aliases:
                score = fuzzy_score(vendor_name, alias)
                if score >= CACHE_HIT_THRESHOLD and (best is None or score > best[1]):
                    best = (entry, score, alias)
        return best

    def add_verified(
        self,
        domain: str,
        parent_company: str,
        alias: str,
        confidence: float,
        epoch: int,
    ) -> None:
        for entry in self.entries:
            if entry.domain == domain:
                if alias not in entry.aliases:
                    entry.aliases.append(alias)
                return
        self.entries.append(
            CacheEntry(
                domain=domain,
                parent_company=parent_company,
                aliases=[alias],
                confidence=confidence,
                verified_epoch=epoch,
            )
        )

    def to_dict(self) -> dict:
        return {
            "entries": [
                {
                    "domain": e.domain,
                    "parent_company": e.parent_company,
                    "aliases": e.aliases,
                    "confidence": e.confidence,
                    "verified_epoch": e.verified_epoch,
                    "verified_by": e.verified_by,
                }
                for e in self.entries
            ]
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
