#!/usr/bin/env python3
"""CLI entry point for the agentic vendor entity resolution POC.

Two modes of use:
  Ad hoc     - resolve a single vendor from the terminal
  Batch      - upload a CSV of vendors, get a results CSV back

Two output shapes (see README for field definitions):
  Ad hoc / user-facing - vendor, parent, relationship type, confidence, domain
  Auditable             - + full reasoning, tool-call log, sources

Runs against bundled synthetic data in --mode mock (default, no API key
needed) or against a real OpenAI model in --mode live (requires
OPENAI_API_KEY). Mock mode only has canned answers for the bundled
synthetic vendors (see data/synthetic_vendors.csv) -- that's what makes the
example run in results/ reproducible without hitting any API.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from agent.pipeline import ResolutionPipeline, Vendor
from evaluation.judge import Verdict, grade_live, grade_mock

ROOT = Path(__file__).resolve().parent


def run_one(pipeline: ResolutionPipeline, vendor: Vendor):
    trace = pipeline.resolve(vendor)
    trace_dict = trace.to_dict()
    judge_result = grade_mock(trace_dict) if pipeline.mode == "mock" else grade_live(trace_dict)

    if judge_result.verdict == Verdict.PASS and trace.final_answer.get("relationship_type") != "cache_hit":
        fa = trace.final_answer
        pipeline.cache.add_verified(
            domain=fa["domain"],
            parent_company=fa["resolved_parent"],
            alias=vendor.vendor_name,
            confidence=fa["confidence"],
            epoch=pipeline.epoch,
        )
    return trace, judge_result


def format_ad_hoc(trace, judge_result) -> dict:
    fa = trace.final_answer or {}
    return {
        "vendor_name": trace.vendor_name,
        "resolved_parent": fa.get("resolved_parent"),
        "relationship_type": fa.get("relationship_type"),
        "confidence": fa.get("confidence"),
        "parent_domain": fa.get("domain"),
        "status": trace.status,
        "judge_verdict": judge_result.verdict.value,
    }


def format_auditable(trace, judge_result) -> dict:
    fa = trace.final_answer or {}
    return {
        "vendor_id": trace.vendor_id,
        "vendor_name": trace.vendor_name,
        "resolved_parent": fa.get("resolved_parent"),
        "confidence": fa.get("confidence"),
        "relationship_type": fa.get("relationship_type"),
        "reasoning": trace.reasoning,
        "parent_domain": fa.get("domain"),
        "sources": [e["source"] for e in trace.evidence],
        "status": trace.status,
        "judge_verdict": judge_result.verdict.value,
        "judge_notes": judge_result.notes,
        "tool_call_log": trace.steps,
    }


def cmd_ad_hoc(args) -> None:
    pipeline = ResolutionPipeline(mode=args.mode)
    vendor = Vendor(vendor_id=args.vendor_id or "adhoc", vendor_name=args.vendor, vendor_address=args.address or "")
    trace, judge_result = run_one(pipeline, vendor)
    payload = format_auditable(trace, judge_result) if args.audit else format_ad_hoc(trace, judge_result)
    print(json.dumps(payload, indent=2))


def cmd_batch(args) -> None:
    pipeline = ResolutionPipeline(mode=args.mode)
    with open(args.input, newline="") as f:
        vendors = [
            Vendor(vendor_id=r["vendor_id"], vendor_name=r["vendor_name"], vendor_address=r.get("vendor_address", ""))
            for r in csv.DictReader(f)
        ]

    rows = []
    verdict_counts: dict[str, int] = {}
    for vendor in vendors:
        trace, judge_result = run_one(pipeline, vendor)
        rows.append(format_auditable(trace, judge_result))
        verdict_counts[judge_result.verdict.value] = verdict_counts.get(judge_result.verdict.value, 0) + 1

    fieldnames = list(rows[0].keys())
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            flat["sources"] = json.dumps(flat["sources"])
            flat["judge_notes"] = json.dumps(flat["judge_notes"])
            flat["tool_call_log"] = json.dumps(flat["tool_call_log"])
            writer.writerow(flat)

    if args.cache_out:
        pipeline.cache.save(Path(args.cache_out))

    print(f"Resolved {len(rows)} vendors -> {args.output}", file=sys.stderr)
    print(f"Judge verdicts: {verdict_counts}", file=sys.stderr)
    if args.cache_out:
        print(f"Verified Resolution Cache written -> {args.cache_out}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["mock", "live"], default="mock", help="mock (default, no API key) or live (requires OPENAI_API_KEY)")

    single = parser.add_argument_group("ad hoc (single vendor)")
    single.add_argument("--vendor", help="Vendor name to resolve")
    single.add_argument("--address", default="", help="Vendor address, if known (used for tie-breaking)")
    single.add_argument("--vendor-id", help="Optional vendor id, for matching bundled mock data (e.g. V004)")
    single.add_argument("--audit", action="store_true", help="Print the full auditable record instead of the short ad hoc summary")

    batch = parser.add_argument_group("batch (CSV upload)")
    batch.add_argument("--input", help="Path to a CSV with vendor_id,vendor_name,vendor_address columns")
    batch.add_argument("--output", default="results.csv", help="Path to write the results CSV")
    batch.add_argument("--cache-out", help="Optional path to save the updated Verified Resolution Cache")

    args = parser.parse_args()

    if args.vendor:
        cmd_ad_hoc(args)
    elif args.input:
        cmd_batch(args)
    else:
        parser.error("Provide --vendor for an ad hoc lookup, or --input for a batch run.")


if __name__ == "__main__":
    main()
