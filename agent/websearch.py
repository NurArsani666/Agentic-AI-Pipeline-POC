"""Step 4 of the resolution funnel: targeted web search fallback.

Only reached when the catalog (as-is + abbreviation) and the agent's own
knowledge both failed to resolve the vendor. Captures a source for every
claim -- required for the LLM-as-judge grounding check later.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WebSearchResult:
    found: bool
    summary: str
    resolved_parent: str | None = None
    domain: str | None = None
    relationship_type: str | None = None
    candidates: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def search_mock(vendor_id: str, index_path: Path) -> WebSearchResult:
    data = json.loads(index_path.read_text())
    entry = data.get(vendor_id)
    if not entry:
        return WebSearchResult(found=False, summary="No information found.", sources=[])
    return WebSearchResult(
        found=entry["found"],
        summary=entry["summary"],
        resolved_parent=entry.get("resolved_parent"),
        domain=entry.get("domain"),
        relationship_type=entry.get("relationship_type"),
        candidates=entry.get("candidates", []),
        sources=entry.get("sources", []),
    )


def search_live(query: str, model: str = "gpt-4o-mini") -> WebSearchResult:
    """Best-effort live web search using OpenAI's hosted web-search tool.

    Requires a model/account with web-search tool access. Falls back to a
    clear error if unavailable -- this repo's mock mode is the reliable way
    to see the full pipeline behavior without any external dependency.
    """
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.responses.create(
        model=model,
        tools=[{"type": "web_search_preview"}],
        input=(
            "Research this vendor and determine its ultimate corporate parent "
            "company, if any (consider acquisitions, rebrands, subsidiaries). "
            f'Vendor: "{query}"\n\n'
            "Respond as JSON only: {\"found\": bool, \"summary\": string, "
            "\"resolved_parent\": string or null, \"domain\": string or null, "
            "\"relationship_type\": string or null, \"sources\": [string]}"
        ),
    )
    text = resp.output_text
    data = json.loads(text)
    return WebSearchResult(
        found=data.get("found", False),
        summary=data.get("summary", ""),
        resolved_parent=data.get("resolved_parent"),
        domain=data.get("domain"),
        relationship_type=data.get("relationship_type"),
        sources=data.get("sources", []),
    )
