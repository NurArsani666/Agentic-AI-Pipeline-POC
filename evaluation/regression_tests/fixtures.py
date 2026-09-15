"""Hand-authored trace fixtures for testing the LLM-as-judge in isolation.

These are NOT traces produced by a live pipeline run -- they're small,
deliberately-crafted examples (some good, some flawed) used to verify the
judge grades correctly on each of its four checks. A judge is only as
trustworthy as its own test suite; this is that suite's core, expanded to
35 cases (parameterized variants of these) in the real project.
"""

PASS_CATALOG_EASY = {
    "vendor_id": "T001",
    "vendor_name": "Ashgrove Partners",
    "status": "resolved",
    "steps": [
        {"step": 1, "tool": "catalog_search_as_is", "reason": "Try catalog match using the vendor name as-is.",
         "query": "Ashgrove Partners", "result_summary": "Exact match, 100%."},
    ],
    "evidence": [],
    "candidates_considered": [],
    "final_answer": {"resolved_parent": "Ashgrove Partners", "domain": "ashgrovepartners.com",
                      "confidence": 0.97, "relationship_type": "catalog_as_is_match"},
    "reasoning": "Exact catalog match, no ambiguity.",
}

PASS_TIE_BREAK_USED_CORRECTLY = {
    "vendor_id": "T002",
    "vendor_name": "Sterling Partners LLC",
    "status": "resolved",
    "steps": [
        {"step": 1, "tool": "catalog_search_as_is", "reason": "Try catalog match as-is.",
         "query": "Sterling Partners LLC", "result_summary": "Two candidates near threshold."},
        {"step": 2, "tool": "web_search", "reason": "Disambiguate between two similarly named firms.",
         "query": "Sterling Partners LLC parent company", "result_summary": "Two distinct firms found."},
        {"step": 3, "tool": "tie_break", "reason": "Two candidates plausible; use vendor address.",
         "query": "200 W Madison St, Chicago, IL", "result_summary": "Matched Sterling Partners Advisory (Chicago)."},
    ],
    "evidence": [
        {"claim": "Two firms named Sterling Partners exist: Capital (NY) and Advisory (Chicago).",
         "source": "https://www.bizwire.example/sterling-partners-directory", "supports_final_answer": True},
        {"claim": "Vendor address matches Sterling Partners Advisory's known Chicago address.",
         "source": "vendor_address_field", "supports_final_answer": True},
    ],
    "candidates_considered": [
        {"resolved_parent": "Sterling Partners Capital", "domain": "sterlingpartnerscapital.com", "address": "1 Liberty Plaza, New York, NY"},
        {"resolved_parent": "Sterling Partners Advisory", "domain": "sterlingpartnersadvisory.com", "address": "200 W Madison St, Chicago, IL"},
    ],
    "final_answer": {"resolved_parent": "Sterling Partners Advisory", "domain": "sterlingpartnersadvisory.com",
                      "confidence": 0.90, "relationship_type": "web_search_tie_break"},
    "reasoning": "Two plausible candidates; resolved via address tie-break.",
}

FAIL_PROCESS_SKIPPED_TIE_BREAK = {
    "vendor_id": "T003",
    "vendor_name": "Sterling Partners LLC",
    "status": "resolved",
    "steps": [
        {"step": 1, "tool": "catalog_search_as_is", "reason": "Try catalog match as-is.",
         "query": "Sterling Partners LLC", "result_summary": "Two candidates near threshold."},
        {"step": 2, "tool": "web_search", "reason": "Disambiguate between two similarly named firms.",
         "query": "Sterling Partners LLC parent company", "result_summary": "Two distinct firms found."},
    ],
    "evidence": [
        {"claim": "Two firms named Sterling Partners exist: Capital (NY) and Advisory (Chicago).",
         "source": "https://www.bizwire.example/sterling-partners-directory", "supports_final_answer": True},
    ],
    "candidates_considered": [
        {"resolved_parent": "Sterling Partners Capital", "domain": "sterlingpartnerscapital.com", "address": "1 Liberty Plaza, New York, NY"},
        {"resolved_parent": "Sterling Partners Advisory", "domain": "sterlingpartnersadvisory.com", "address": "200 W Madison St, Chicago, IL"},
    ],
    # BUG: picked the first candidate arbitrarily instead of calling tie_break.
    "final_answer": {"resolved_parent": "Sterling Partners Capital", "domain": "sterlingpartnerscapital.com",
                      "confidence": 0.80, "relationship_type": "web_search_resolved"},
    "reasoning": "Two candidates were found; picked the first one.",
}

FAIL_PROCESS_WRONG_ORDER = {
    "vendor_id": "T004",
    "vendor_name": "Kestrel Data Systems Corp",
    "status": "resolved",
    "steps": [
        # BUG: jumped straight to web search, skipping the cheap catalog checks.
        {"step": 1, "tool": "web_search", "reason": "Search for the vendor's parent company.",
         "query": "Kestrel Data Systems Corp parent company", "result_summary": "Found a match."},
    ],
    "evidence": [
        {"claim": "Kestrel Data Systems is listed in an industry directory with no parent noted.",
         "source": "https://www.directory.example/kestrel-data-systems", "supports_final_answer": True},
    ],
    "candidates_considered": [],
    "final_answer": {"resolved_parent": "Kestrel Data Systems", "domain": "kestreldata.com",
                      "confidence": 0.85, "relationship_type": "web_search_resolved"},
    "reasoning": "Resolved via web search.",
}

FAIL_GROUNDING_CONTRADICTION = {
    "vendor_id": "T005",
    "vendor_name": "Boston Consulting Group (illustrative)",
    "status": "resolved",
    "steps": [
        {"step": 1, "tool": "catalog_search_as_is", "reason": "Try catalog match as-is.",
         "query": "Boston Consulting Group", "result_summary": "No confident match."},
        {"step": 2, "tool": "catalog_search_abbreviation", "reason": "Retry with abbreviation.",
         "query": "BCG", "result_summary": "No confident match."},
        {"step": 3, "tool": "agent_reasoning", "reason": "Propose a candidate from general knowledge.",
         "query": "Boston Consulting Group", "result_summary": "No confident guess."},
        {"step": 4, "tool": "web_search", "reason": "Search for ownership/acquisition evidence.",
         "query": "Boston Consulting Group parent company", "result_summary": "Found acquisition evidence."},
    ],
    "evidence": [
        # The evidence says it was acquired -- but the final answer below still
        # names the original company as its own parent. That's the contradiction.
        {"claim": "Boston Consulting Group was acquired by Bank of America in 2024.",
         "source": "https://www.example-news.test/bcg-boa-acquisition", "supports_final_answer": False},
    ],
    "candidates_considered": [],
    "final_answer": {"resolved_parent": "Boston Consulting Group", "domain": "bcg.com",
                      "confidence": 0.75, "relationship_type": "web_search_resolved"},
    "reasoning": "Evidence says it was acquired by Bank of America, but the final answer still names Boston Consulting Group as its own parent -- the conclusion doesn't follow from the evidence.",
}

FAIL_GROUNDING_MISSING_SOURCE = {
    "vendor_id": "T006",
    "vendor_name": "Aurelia Textile Works",
    "status": "resolved",
    "steps": [
        {"step": 1, "tool": "catalog_search_as_is", "reason": "Try catalog match as-is.",
         "query": "Aurelia Textile Works", "result_summary": "No confident match."},
        {"step": 2, "tool": "catalog_search_abbreviation", "reason": "Retry with abbreviation.",
         "query": "ATW", "result_summary": "No confident match."},
        {"step": 3, "tool": "agent_reasoning", "reason": "Propose a candidate from general knowledge.",
         "query": "Aurelia Textile Works", "result_summary": "No confident guess."},
        {"step": 4, "tool": "web_search", "reason": "Search for ownership/acquisition evidence.",
         "query": "Aurelia Textile Works parent company", "result_summary": "Found rebrand evidence."},
    ],
    "evidence": [
        # BUG: no source attached to the claim -- ungrounded assertion.
        {"claim": "Aurelia Textile Works rebranded as Aurelia Textiles Group in 2023.", "source": "", "supports_final_answer": True},
    ],
    "candidates_considered": [],
    "final_answer": {"resolved_parent": "Aurelia Textiles Group", "domain": "aureliatextiles.com",
                      "confidence": 0.85, "relationship_type": "web_search_resolved"},
    "reasoning": "Resolved via web search.",
}

NEEDS_REVIEW_INSUFFICIENT_INFO = {
    "vendor_id": "T007",
    "vendor_name": "Bramblewood & Finch Studio",
    "status": "needs_review",
    "steps": [
        {"step": 1, "tool": "catalog_search_as_is", "reason": "Try catalog match as-is.",
         "query": "Bramblewood & Finch Studio", "result_summary": "No confident match."},
        {"step": 2, "tool": "catalog_search_abbreviation", "reason": "Retry with abbreviation.",
         "query": "BFS", "result_summary": "No confident match."},
        {"step": 3, "tool": "agent_reasoning", "reason": "Propose a candidate from general knowledge.",
         "query": "Bramblewood & Finch Studio", "result_summary": "No confident guess."},
        {"step": 4, "tool": "web_search", "reason": "Search for ownership/acquisition evidence.",
         "query": "Bramblewood & Finch Studio parent company", "result_summary": "No information found."},
    ],
    "evidence": [],
    "candidates_considered": [],
    "final_answer": {},
    "reasoning": "No reliable public information found; appears to be a small independent business.",
}

ALL_FIXTURES = {
    "pass_catalog_easy": (PASS_CATALOG_EASY, "PASS"),
    "pass_tie_break_used_correctly": (PASS_TIE_BREAK_USED_CORRECTLY, "PASS"),
    "fail_process_skipped_tie_break": (FAIL_PROCESS_SKIPPED_TIE_BREAK, "FAIL-PROCESS"),
    "fail_process_wrong_order": (FAIL_PROCESS_WRONG_ORDER, "FAIL-PROCESS"),
    "fail_grounding_contradiction": (FAIL_GROUNDING_CONTRADICTION, "FAIL-GROUNDING"),
    "fail_grounding_missing_source": (FAIL_GROUNDING_MISSING_SOURCE, "FAIL-GROUNDING"),
    "needs_review_insufficient_info": (NEEDS_REVIEW_INSUFFICIENT_INFO, "NEEDS-REVIEW"),
}
