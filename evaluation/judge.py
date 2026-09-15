"""LLM-as-Judge evaluation layer.

There's no ground-truth label set, so the judge doesn't grade "was the
final name right" -- it grades whether the agent's *process* was
defensible. Four checks, mirroring the real system:

  1. Process      -- right steps, right order (cache -> catalog as-is ->
                      catalog abbreviation -> reasoning -> web search),
                      and the tie-break tool was called whenever more than
                      one candidate was ever on the table.
  2. Grounding     -- every claim is backed by a real captured source, and
                      the final answer doesn't contradict the evidence.
  3. Needs-review  -- reserved for genuinely under-evidenced cases, not a
                      process or grounding failure.
  4. (logic)       -- folded into grounding here: does the evidence
                      actually support the stated conclusion.

Verdicts: PASS (-> Verified Resolution Cache) / FAIL-PROCESS / FAIL-GROUNDING
(both -> human review) / NEEDS-REVIEW (-> human review, different reason).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum

# Tools that count as "escalating past the internal catalog". If any of these
# appear in a trace, catalog_search_as_is must appear too -- the agent has to
# have checked internal information before reasoning or searching externally.
ESCALATION_TOOLS = {"agent_reasoning", "web_search"}


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL_PROCESS = "FAIL-PROCESS"
    FAIL_GROUNDING = "FAIL-GROUNDING"
    NEEDS_REVIEW = "NEEDS-REVIEW"


@dataclass
class JudgeResult:
    verdict: Verdict
    process_ok: bool
    grounding_ok: bool
    notes: list[str] = field(default_factory=list)


def _check_process(trace: dict) -> tuple[bool, list[str]]:
    notes = []
    tools_present = {s["tool"] for s in trace.get("steps", [])}

    if tools_present & ESCALATION_TOOLS and "catalog_search_as_is" not in tools_present:
        notes.append(
            "Escalated to reasoning and/or web search without first checking "
            "the internal catalog."
        )

    candidates = trace.get("candidates_considered", [])
    if len(candidates) > 1 and "tie_break" not in tools_present:
        notes.append(
            f"{len(candidates)} plausible candidates were on the table but the "
            "tie-break tool was never called."
        )

    return (len(notes) == 0), notes


def _check_grounding(trace: dict) -> tuple[bool, list[str]]:
    notes = []
    evidence = trace.get("evidence", [])
    for e in evidence:
        if not e.get("source"):
            notes.append(f"Claim \"{e.get('claim')}\" has no source attached.")
        if e.get("supports_final_answer") is False:
            notes.append(
                f"Evidence \"{e.get('claim')}\" does not support the final answer "
                f"\"{trace.get('final_answer', {}).get('resolved_parent')}\"."
            )
    return (len(notes) == 0), notes


def grade_mock(trace: dict) -> JudgeResult:
    if trace.get("status") == "needs_review":
        return JudgeResult(
            verdict=Verdict.NEEDS_REVIEW,
            process_ok=True,
            grounding_ok=True,
            notes=[trace.get("reasoning", "Insufficient evidence to resolve confidently.")],
        )

    process_ok, process_notes = _check_process(trace)
    grounding_ok, grounding_notes = _check_grounding(trace)

    if not process_ok:
        return JudgeResult(Verdict.FAIL_PROCESS, process_ok, grounding_ok, process_notes)
    if not grounding_ok:
        return JudgeResult(Verdict.FAIL_GROUNDING, process_ok, grounding_ok, grounding_notes)
    return JudgeResult(Verdict.PASS, True, True, ["All checks passed."])


def grade_live(trace: dict, model: str = "gpt-4o-mini") -> JudgeResult:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    prompt = (
        "You are grading an AI agent's vendor-entity-resolution trace. There is "
        "no ground truth for the final answer, so do NOT grade whether the name "
        "is correct. Grade the PROCESS instead:\n"
        "1. Did it take the right steps in the right order (catalog checks before "
        "reasoning, reasoning before web search), and call the tie-break tool "
        "whenever multiple candidates were plausible?\n"
        "2. Is every claim backed by a real source, and does the final answer "
        "avoid contradicting the evidence?\n\n"
        f"Trace:\n{json.dumps(trace, indent=2)}\n\n"
        'Respond as JSON: {"verdict": "PASS"|"FAIL-PROCESS"|"FAIL-GROUNDING"|"NEEDS-REVIEW", '
        '"process_ok": bool, "grounding_ok": bool, "notes": [string]}'
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    return JudgeResult(
        verdict=Verdict(data["verdict"]),
        process_ok=data.get("process_ok", False),
        grounding_ok=data.get("grounding_ok", False),
        notes=data.get("notes", []),
    )
