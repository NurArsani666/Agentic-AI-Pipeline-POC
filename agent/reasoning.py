"""Step 3 of the resolution funnel: agent reasons from its own knowledge.

Before spending a web search, the agent proposes a likely parent from
what it already "knows" -- no browsing -- and checks whether that guess
exists in the catalog. This mirrors the real system's cheapest LLM step:
one call, no tools, before escalating further.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .catalog import CatalogRow, MATCH_THRESHOLD
from .normalize import fuzzy_score


@dataclass
class KnowledgeGuess:
    guess: str | None
    rationale: str


def guess_from_knowledge_mock(vendor_id: str, knowledge_path: Path) -> KnowledgeGuess:
    data = json.loads(knowledge_path.read_text())
    entry = data.get(vendor_id)
    if not entry:
        return KnowledgeGuess(guess=None, rationale="No confident guess available from prior knowledge.")
    return KnowledgeGuess(guess=entry["guess"], rationale=entry["rationale"])


def guess_from_knowledge_live(vendor_name: str, model: str = "gpt-4o-mini") -> KnowledgeGuess:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    prompt = (
        "You are helping resolve a vendor record to its corporate parent company. "
        "Do NOT search the web. Based only on general knowledge you already have, "
        "propose the most likely parent/ultimate owner for this vendor name, if you "
        "recognize a naming pattern (subsidiary, regional office, alias). "
        "If you don't have a confident guess, say so.\n\n"
        f'Vendor name: "{vendor_name}"\n\n'
        "Respond as JSON: {\"guess\": string or null, \"rationale\": string}"
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    return KnowledgeGuess(guess=data.get("guess"), rationale=data.get("rationale", ""))


def check_catalog_for_guess(guess: str, catalog: list[CatalogRow]) -> tuple[CatalogRow, float] | None:
    if not guess:
        return None
    scored = sorted(
        ((row, fuzzy_score(guess, row.catalog_name)) for row in catalog),
        key=lambda t: t[1],
        reverse=True,
    )
    if scored and scored[0][1] >= MATCH_THRESHOLD:
        return scored[0]
    return None
