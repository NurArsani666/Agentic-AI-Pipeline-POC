"""Tie-break tool: disambiguate between competing candidate parents using
the vendor record's own address. Used whenever a step surfaces two or more
plausible candidates that can't be separated on name evidence alone."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TieBreakResult:
    resolved: bool
    chosen_index: int | None
    reason: str


def break_tie(vendor_address: str, candidates: list[dict]) -> TieBreakResult:
    if not vendor_address:
        return TieBreakResult(
            resolved=False,
            chosen_index=None,
            reason="No vendor address available to use as a tie-breaking signal.",
        )

    vendor_tokens = {t.strip(",.").lower() for t in vendor_address.split()}
    best_idx, best_overlap = None, 0
    for i, c in enumerate(candidates):
        cand_tokens = {t.strip(",.").lower() for t in c.get("address", "").split()}
        overlap = len(vendor_tokens & cand_tokens)
        if overlap > best_overlap:
            best_overlap, best_idx = overlap, i

    if best_idx is None or best_overlap == 0:
        return TieBreakResult(
            resolved=False,
            chosen_index=None,
            reason="Vendor address did not match any candidate's known address closely enough.",
        )

    chosen = candidates[best_idx]
    return TieBreakResult(
        resolved=True,
        chosen_index=best_idx,
        reason=(
            f"Vendor address \"{vendor_address}\" matches the known address for "
            f"\"{chosen.get('resolved_parent')}\" ({chosen.get('address')})."
        ),
    )
