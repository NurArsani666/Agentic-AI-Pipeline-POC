# Agentic Vendor Entity Resolution — Sanitized POC

> This repository is a sanitized proof-of-concept inspired by an agentic
> entity-resolution workflow I built during my internship at Warburg Pincus,
> where it resolved 5,000 real vendor records at 95% accuracy, 115x faster
> than the manual process it replaced, and was approved for firm-wide
> deployment. The original data, prompts, and internal infrastructure are
> proprietary and are **not** included here.
>
> This POC recreates the real decision logic — the deterministic-first
> resolution funnel, the domain-keyed verified cache, and the LLM-as-judge
> evaluation harness — on 100% synthetic, fictional vendor data, so the
> architecture and evaluation approach are inspectable and runnable.
>
> The production system additionally ran a 35-case regression suite across
> separated evaluation / testing / main environments. This POC collapses
> that into one simple, readable repo for demonstration — the resolution
> logic and evaluation approach below are faithful to the real design, just
> smaller in scope.
>
> Full case study (business problem, role, results, lessons learned):
> [Agentic AI for Vendor Entity Resolution](https://www.notion.so/Agentic-AI-for-Vendor-Entity-Resolution-3dc496721d8d81ceaf31c5df908cb4c4)

## What this demonstrates

- A **deterministic-first** resolution funnel that only calls an LLM when
  cheaper signals (catalog fuzzy match, a verified cache) fail — not an
  LLM call on every record
- A **domain-keyed Verified Resolution Cache** that turns every confirmed
  resolution into free, instant answers for every future name variant of
  the same company
- An **LLM-as-judge** evaluation harness that grades the agent's *process*
  and *grounding*, not just whether the final name looks right — there's
  no ground-truth label set to check against
- **Structured, evidence-grounded output**, not free-form LLM text: every
  claim carries a source, every decision carries a tool-call log

## Architecture

### 1. The resolution funnel

Cheapest, most reliable signal first; the LLM is a last resort, not the
first move.

```
 Vendor name + address (if any)
              |
              v
 0. Verified Resolution Cache — fuzzy-match name against aliases
    already confirmed in a prior epoch
              |
     cache hit? --YES--> Resolved instantly (no catalog lookup, no LLM call)
              |NO
              v
 1. Catalog fuzzy-match — query name AS-IS, top-5 candidates
              |
     score >= 95%? --YES--> is catalog entry stale (>18mo)? --YES--> verify via
              |                                                       web search;
              |                                                       override if
              |                                                       evidence
              |                                                       disagrees
              |NO                                            |NO --> Resolved
              v
 2. Catalog fuzzy-match — retry with ABBREVIATION (e.g. "BCG")
              |
     score >= 95%? --YES--> (same stale check as above) --> Resolved
              |NO
              v
 3. Agent reasons from its own knowledge (no browsing) — proposes a
    likely parent, checks whether THAT name exists in the catalog
              |
        found? --YES--> Resolved
              |NO
              v
 4. Web search — find ownership/acquisition evidence, resolve the
    parent, capture the source + domain
              |
   multiple / tied candidates? --YES--> Tie-Break Tool: pull the
              |                          vendor's address, compare
              |NO                        against each candidate's
              v                          known address, resolve
          Resolved (parent + confidence + reasoning + sources)
              |
              v
      Graded PASS by the judge? --YES--> written into the Verified
                                          Resolution Cache for next time
```

Tools available to the agent: **Catalog Search** (fuzzy match), **Web
Search** (targeted research + evidence capture), **Tie-Break Lookup**
(pulls the vendor's address to disambiguate).

### 2. Evaluation: LLM-as-judge + human-in-the-loop

There's no ground-truth label set, so the judge grades *process*, not
"was the name right."

```
 Agent resolves vendor
        |
        v
 LLM-as-Judge grades the full trace on 4 checks:
   - Process:    catalog checked before reasoning/web search? tie-break
                 tool called whenever multiple candidates were plausible?
   - Grounding:  every claim backed by a real source? does the final
                 answer avoid contradicting the evidence?
        |
  +-----+-------------+--------------------+
  v     v              v                    v
PASS  FAIL-PROCESS  FAIL-GROUNDING     NEEDS-REVIEW
  |        +--------------+--------------------+
  v                       v
Verified Resolution   Human Review (engineer + domain expert)
Cache (keyed by       -> confirms the correct answer
parent domain)        -> feeds back to fix agent/judge prompts
  ^                       |
  +-----------------------+
   next matching vendor    next epoch: agent + judge get better,
   hits cache instead of   cache grows, fewer records need a human
   re-searching
```

Verdicts: **PASS** → ships, written to the cache · **FAIL-PROCESS** /
**FAIL-GROUNDING** / **NEEDS-REVIEW** → routed to a human reviewer, whose
correction becomes feedback for the next epoch.

## Quickstart

```bash
git clone <this repo>
cd Agentic-AI-Pipeline-POC
pip install -r requirements.txt   # only needed for --mode live

# Ad hoc — resolve a single vendor from the terminal (mock mode, no API key)
python run.py --vendor "Meridian Health Partners Group AG" --vendor-id V015

# Same lookup, full auditable record (tool-call log, sources, judge notes)
python run.py --vendor "Brightwell Logistics (Midwest) LLC" --vendor-id V004 --audit

# Batch — upload a CSV of vendors, get a results CSV back
python run.py --input data/synthetic_vendors.csv --output results.csv \
  --cache-out verified_cache_after_run.json

# Judge regression suite (7 hand-crafted good/bad traces, no API key needed)
python evaluation/regression_tests/run_tests.py

# Live mode — real OpenAI calls instead of the bundled mock data
export OPENAI_API_KEY=sk-...
python run.py --vendor "Some Real Company Inc." --mode live --audit
```

`--mode mock` (the default) only has canned answers for the 15 vendors
bundled in `data/synthetic_vendors.csv` — that's what makes the committed
example run in `results/example_run/` fully reproducible with zero setup.
Try any vendor name from that file to see every branch of the funnel.
`--mode live` runs the same decision logic against a real OpenAI model for
an arbitrary vendor name.

## What each mode returns

- **Ad hoc** (default): vendor name, resolved parent, relationship type
  (catalog match / knowledge-guess / web-search / cache-hit / standalone),
  confidence score, parent domain
- **Auditable** (`--audit` flag, or always in batch mode): everything
  above, **plus** full reasoning, the complete tool-call log (every tool
  called, why, and what it found), and the source URLs

## Repo structure

```
data/
  synthetic_vendors.csv        15 fictional, deliberately messy vendor
                                records (missing addresses, aliases,
                                subsidiary naming, rebrands, stale-catalog
                                cases — mirrors the real data problems)
  synthetic_catalog.csv        fictional internal "catalog" — intentionally
                                incomplete and sometimes stale, just like
                                the real one
  mock_agent_knowledge.json    mock mode's stand-in for "agent reasons from
                                its own knowledge" (step 3)
  mock_web_index.json          mock mode's stand-in for the web-search tool
  verified_cache_seed.json     starting state of the Verified Resolution
                                Cache, as if one prior epoch had already run

agent/
  normalize.py                 name normalization + fuzzy matching (stdlib only)
  catalog.py                   steps 1-2: catalog match, as-is + abbreviation,
                                staleness detection
  reasoning.py                 step 3: agent-knowledge guess -> catalog check
  websearch.py                 step 4: mocked/live web search fallback
  tiebreak.py                  address-based candidate disambiguation
  cache.py                     Verified Resolution Cache (domain-keyed)
  pipeline.py                  orchestrator tying every step together

evaluation/
  judge.py                     LLM-as-judge: process / grounding / needs-review
  regression_tests/
    fixtures.py                 7 hand-crafted good/bad traces
    run_tests.py                 runs the judge against them, no deps

results/example_run/           pre-generated outputs — inspect without
                                running anything (see SUMMARY.md)

run.py                         CLI: ad hoc + batch modes
```

## Example

Input: `Sterling Partners LLC`, address `200 W Madison St, Chicago, IL`

The catalog contains two similarly-named entries — Sterling Partners
Capital (New York) and Sterling Partners Advisory (Chicago) — that neither
name-based match nor web search alone can disambiguate. The tie-break tool
pulls the vendor's address and resolves it to the Chicago entity:

```json
{
  "vendor_name": "Sterling Partners LLC",
  "resolved_parent": "Sterling Partners Advisory",
  "relationship_type": "web_search_tie_break",
  "confidence": 0.85,
  "parent_domain": "sterlingpartnersadvisory.com",
  "status": "resolved",
  "judge_verdict": "PASS"
}
```

See `results/example_run/SUMMARY.md` for all 15 vendors and every path
through the funnel, including a case where a stale catalog entry gets
caught and corrected by a fresh web search.

## Why this design

The interesting engineering problem wasn't "can an LLM guess a parent
company" — it was building something reliable and auditable enough to
trust at scale, with data that was often incomplete and an internal
catalog that wasn't always right either. That meant: try the cheapest,
most deterministic signal first; make every LLM step evidence-grounded and
loggable; and evaluate the *process*, not just the answer, since there was
no ground truth to check against upfront. The Verified Resolution Cache is
what made it compound over time instead of repeating full-cost work on
records the system had effectively already seen.

## Tech stack

Python (stdlib for mock mode), OpenAI API (live mode only), no external
dependencies required to run the default demo.
