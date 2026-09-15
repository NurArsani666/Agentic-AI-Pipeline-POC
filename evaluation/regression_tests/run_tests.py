#!/usr/bin/env python3
"""Regression suite for the LLM-as-judge (mock/rule-based grading path).

Run with: python evaluation/regression_tests/run_tests.py
No dependencies beyond the standard library.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluation.judge import grade_mock
from evaluation.regression_tests.fixtures import ALL_FIXTURES


def main() -> int:
    failures = 0
    for name, (trace, expected) in ALL_FIXTURES.items():
        result = grade_mock(trace)
        ok = result.verdict.value == expected
        status = "ok" if ok else "MISMATCH"
        print(f"[{status}] {name}: expected {expected}, got {result.verdict.value}")
        if not ok:
            failures += 1
            for note in result.notes:
                print(f"    note: {note}")

    print(f"\n{len(ALL_FIXTURES) - failures}/{len(ALL_FIXTURES)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
