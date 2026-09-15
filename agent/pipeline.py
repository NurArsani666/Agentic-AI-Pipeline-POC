"""Orchestrator: the resolution funnel end to end.

  0. Verified Resolution Cache lookup (domain-keyed, from prior epochs)
  1. Catalog match, as-is (fuzzy, >=95%)
  2. Catalog match, abbreviation retry (fuzzy, >=95%)
     -> if a catalog match is found in 1 or 2 but the entry is stale,
        confirm with a verification web search before trusting it
     -> if the top two catalog candidates are tied, use the tie-break tool
  3. Agent reasons from its own knowledge -> checks catalog for that guess
  4. Web search fallback -> resolve, or surface tied candidates -> tie-break
  5. Anything still unresolved -> NEEDS-REVIEW, routed to a human

Every branch produces a full trace (steps + evidence + final answer) that
the LLM-as-judge grades, and every PASS gets written into the cache.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import catalog as catalog_mod
from . import reasoning
from . import tiebreak
from . import websearch
from .cache import VerifiedResolutionCache
from .normalize import abbreviate

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class Vendor:
    vendor_id: str
    vendor_name: str
    vendor_address: str = ""


@dataclass
class ResolutionTrace:
    vendor_id: str
    vendor_name: str
    vendor_address: str
    status: str  # "resolved" | "needs_review"
    steps: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    candidates_considered: list[dict] = field(default_factory=list)
    final_answer: dict = field(default_factory=dict)
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "vendor_id": self.vendor_id,
            "vendor_name": self.vendor_name,
            "vendor_address": self.vendor_address,
            "status": self.status,
            "steps": self.steps,
            "evidence": self.evidence,
            "candidates_considered": self.candidates_considered,
            "final_answer": self.final_answer,
            "reasoning": self.reasoning,
        }


class ResolutionPipeline:
    def __init__(self, mode: str = "mock", epoch: int = 2):
        assert mode in ("mock", "live")
        self.mode = mode
        self.epoch = epoch
        self.catalog = catalog_mod.load_catalog(DATA_DIR / "synthetic_catalog.csv")
        self.cache = VerifiedResolutionCache.load(DATA_DIR / "verified_cache_seed.json")

    def resolve(self, vendor: Vendor) -> ResolutionTrace:
        trace = ResolutionTrace(
            vendor_id=vendor.vendor_id,
            vendor_name=vendor.vendor_name,
            vendor_address=vendor.vendor_address,
            status="resolved",
        )

        # Step 0: Verified Resolution Cache
        cache_hit = self.cache.lookup(vendor.vendor_name)
        if cache_hit:
            entry, score, alias = cache_hit
            trace.steps.append({
                "step": 0, "tool": "cache_lookup",
                "reason": "Check the Verified Resolution Cache before any other step.",
                "query": vendor.vendor_name,
                "result_summary": f"Matched alias \"{alias}\" ({score}%) -> {entry.parent_company}.",
            })
            trace.evidence.append({
                "claim": f"\"{alias}\" was verified in epoch {entry.verified_epoch} to resolve to {entry.parent_company} ({entry.domain}).",
                "source": "verified_resolution_cache",
                "supports_final_answer": True,
            })
            trace.final_answer = {
                "resolved_parent": entry.parent_company,
                "domain": entry.domain,
                "confidence": entry.confidence,
                "relationship_type": "cache_hit",
            }
            trace.reasoning = (
                f"\"{vendor.vendor_name}\" matches a previously verified alias for "
                f"{entry.parent_company} ({entry.domain}); resolved directly from the "
                "cache with no catalog lookup or LLM call needed."
            )
            return trace

        # Steps 1-2: catalog match (as-is, then abbreviation)
        cm = catalog_mod.match(vendor.vendor_name, self.catalog)
        tool_name = {
            "as_is": "catalog_search_as_is",
            "abbreviation": "catalog_search_abbreviation",
        }
        if cm:
            # Log the step(s) tried, including a logged miss for as-is if we only
            # resolved on the abbreviation retry.
            if cm.query_used == "abbreviation":
                trace.steps.append({
                    "step": 1, "tool": "catalog_search_as_is",
                    "reason": "Try catalog match using the vendor name as-is (fuzzy, top-5).",
                    "query": vendor.vendor_name,
                    "result_summary": "No candidate reached the 95% match threshold.",
                })
            trace.steps.append({
                "step": len(trace.steps) + 1, "tool": tool_name[cm.query_used],
                "reason": (
                    "Try catalog match using the vendor name as-is (fuzzy, top-5)."
                    if cm.query_used == "as_is" else
                    "As-is match failed; retry with a likely abbreviation of the vendor name."
                ),
                "query": cm.query_string,
                "result_summary": f"Top match \"{cm.top_matches[0][0].catalog_name}\" at {cm.top_matches[0][1]}%.",
            })

            if cm.tied:
                candidates = [
                    {"resolved_parent": row.parent_company, "domain": row.domain, "address": row.address}
                    for row, _ in cm.top_matches[:2]
                ]
                trace.candidates_considered = candidates
                trace.steps.append({
                    "step": len(trace.steps) + 1, "tool": "tie_break",
                    "reason": "Two catalog candidates scored within the tie margin; disambiguate using the vendor's address.",
                    "query": vendor.vendor_address,
                    "result_summary": "See tie-break result.",
                })
                tb = tiebreak.break_tie(vendor.vendor_address, candidates)
                if not tb.resolved:
                    trace.status = "needs_review"
                    trace.reasoning = f"Multiple catalog candidates tied and could not be disambiguated: {tb.reason}"
                    return trace
                chosen = candidates[tb.chosen_index]
                trace.evidence.append({
                    "claim": tb.reason, "source": "vendor_address_field", "supports_final_answer": True,
                })
                trace.final_answer = {
                    "resolved_parent": chosen["resolved_parent"], "domain": chosen["domain"],
                    "confidence": 0.90, "relationship_type": "catalog_tie_break",
                }
                trace.reasoning = f"Catalog produced tied candidates; resolved via address tie-break. {tb.reason}"
                self._maybe_cache(trace)
                return trace

            row, score = cm.top_matches[0]
            if cm.stale:
                trace.steps.append({
                    "step": len(trace.steps) + 1, "tool": "verification_search",
                    "reason": f"Catalog entry last verified {row.last_verified.isoformat()} (>18 months old); confirm before trusting it.",
                    "query": f"{row.catalog_name} parent company ownership",
                    "result_summary": "See verification result.",
                })
                verification = self._websearch(f"verification_{vendor.vendor_id}", f"{row.catalog_name} parent company ownership")
                if verification.found and verification.resolved_parent and verification.resolved_parent != row.parent_company:
                    trace.evidence.append({
                        "claim": verification.summary, "source": verification.sources[0] if verification.sources else "web_search",
                        "supports_final_answer": True,
                    })
                    trace.final_answer = {
                        "resolved_parent": verification.resolved_parent, "domain": verification.domain,
                        "confidence": 0.90, "relationship_type": "catalog_correction",
                    }
                    trace.reasoning = (
                        f"Catalog said \"{row.parent_company}\" but was stale; verification search found: "
                        f"{verification.summary}"
                    )
                else:
                    trace.evidence.append({
                        "claim": verification.summary, "source": verification.sources[0] if verification.sources else "web_search",
                        "supports_final_answer": True,
                    })
                    trace.final_answer = {
                        "resolved_parent": row.parent_company, "domain": row.domain,
                        "confidence": 0.95, "relationship_type": f"catalog_{cm.query_used}_match_confirmed",
                    }
                    trace.reasoning = f"Catalog match confirmed current via verification search: {verification.summary}"
                self._maybe_cache(trace)
                return trace

            trace.final_answer = {
                "resolved_parent": row.parent_company, "domain": row.domain,
                "confidence": 0.97, "relationship_type": f"catalog_{cm.query_used}_match",
            }
            trace.reasoning = f"Catalog fuzzy match on {'the vendor name as-is' if cm.query_used == 'as_is' else 'an abbreviation of the vendor name'} resolved this with no ambiguity ({score}%)."
            self._maybe_cache(trace)
            return trace

        # Catalog fully missed: log both attempted queries
        trace.steps.append({
            "step": 1, "tool": "catalog_search_as_is",
            "reason": "Try catalog match using the vendor name as-is (fuzzy, top-5).",
            "query": vendor.vendor_name, "result_summary": "No candidate reached the 95% match threshold.",
        })
        trace.steps.append({
            "step": 2, "tool": "catalog_search_abbreviation",
            "reason": "As-is match failed; retry with a likely abbreviation of the vendor name.",
            "query": abbreviate(vendor.vendor_name), "result_summary": "No candidate reached the 95% match threshold.",
        })

        # Step 3: agent reasons from its own knowledge
        guess = self._knowledge_guess(vendor)
        trace.steps.append({
            "step": 3, "tool": "agent_reasoning",
            "reason": "No catalog match by name or abbreviation; propose a candidate parent from general knowledge before searching the web.",
            "query": vendor.vendor_name,
            "result_summary": guess.guess or "No confident guess.",
        })
        if guess.guess:
            hit = reasoning.check_catalog_for_guess(guess.guess, self.catalog)
            trace.steps.append({
                "step": 4, "tool": "catalog_search_verify_guess",
                "reason": "Check whether the guessed parent exists in the catalog.",
                "query": guess.guess,
                "result_summary": f"Found \"{hit[0].catalog_name}\" at {hit[1]}%." if hit else "Not found in catalog.",
            })
            if hit:
                row, score = hit
                trace.evidence.append({
                    "claim": guess.rationale, "source": "agent_prior_knowledge", "supports_final_answer": True,
                })
                trace.final_answer = {
                    "resolved_parent": row.parent_company, "domain": row.domain,
                    "confidence": 0.88, "relationship_type": "knowledge_guess_confirmed_in_catalog",
                }
                trace.reasoning = f"{guess.rationale} Confirmed against the catalog ({score}%)."
                self._maybe_cache(trace)
                return trace

        # Step 4: web search fallback
        trace.steps.append({
            "step": len(trace.steps) + 1, "tool": "web_search",
            "reason": "Catalog and internal knowledge could not resolve this vendor; search for ownership/acquisition evidence.",
            "query": vendor.vendor_name, "result_summary": "See web search result.",
        })
        result = self._websearch(vendor.vendor_id, f"{vendor.vendor_name} parent company")

        if result.candidates:
            trace.candidates_considered = result.candidates
            trace.steps.append({
                "step": len(trace.steps) + 1, "tool": "tie_break",
                "reason": "Web search surfaced multiple plausible candidates; disambiguate using the vendor's address.",
                "query": vendor.vendor_address, "result_summary": "See tie-break result.",
            })
            tb = tiebreak.break_tie(vendor.vendor_address, result.candidates)
            if not tb.resolved:
                trace.status = "needs_review"
                trace.reasoning = f"Web search found multiple plausible candidates and could not disambiguate: {tb.reason}"
                return trace
            chosen = result.candidates[tb.chosen_index]
            trace.evidence.append({"claim": result.summary, "source": result.sources[0] if result.sources else "web_search", "supports_final_answer": True})
            trace.evidence.append({"claim": tb.reason, "source": "vendor_address_field", "supports_final_answer": True})
            trace.final_answer = {
                "resolved_parent": chosen["resolved_parent"], "domain": chosen["domain"],
                "confidence": 0.85, "relationship_type": "web_search_tie_break",
            }
            trace.reasoning = f"{result.summary} {tb.reason}"
            self._maybe_cache(trace)
            return trace

        if not result.found:
            trace.status = "needs_review"
            trace.reasoning = result.summary
            return trace

        trace.evidence.append({
            "claim": result.summary, "source": result.sources[0] if result.sources else "web_search",
            "supports_final_answer": True,
        })
        trace.final_answer = {
            "resolved_parent": result.resolved_parent, "domain": result.domain,
            "confidence": 0.85 if result.resolved_parent else 0.80,
            "relationship_type": result.relationship_type or "web_search_resolved",
        }
        trace.reasoning = result.summary
        self._maybe_cache(trace)
        return trace

    def _knowledge_guess(self, vendor: Vendor):
        if self.mode == "mock":
            return reasoning.guess_from_knowledge_mock(vendor.vendor_id, DATA_DIR / "mock_agent_knowledge.json")
        return reasoning.guess_from_knowledge_live(vendor.vendor_name)

    def _websearch(self, key: str, query: str):
        if self.mode == "mock":
            return websearch.search_mock(key, DATA_DIR / "mock_web_index.json")
        return websearch.search_live(query)

    def _maybe_cache(self, trace: ResolutionTrace) -> None:
        """Only PASS-graded resolutions get written to the cache -- the judge
        runs after this, in run.py, and calls back in if it passes."""
        return  # caching is done by the caller after grading, see run.py
