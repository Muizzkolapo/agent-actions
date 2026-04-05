"""Smoke test harness -- run examples through the real CLI with agac-provider.

Usage:
    python -m tests.manual.smoke_test              # run all examples
    python -m tests.manual.smoke_test support_resolution  # run one example
"""

from __future__ import annotations

import sys

from tests.manual.smoke_test.registry import EXAMPLES
from tests.manual.smoke_test.runner import cleanup, run_example
from tests.manual.smoke_test.verifier import print_results, run_checks


def main() -> int:
    # Filter by name if provided
    names = sys.argv[1:]
    examples = [e for e in EXAMPLES if e.name in names] if names else EXAMPLES

    if not examples:
        print(f"No examples matched: {names}")
        print(f"Available: {[e.name for e in EXAMPLES]}")
        return 1

    total_pass = 0
    total_fail = 0

    for example in examples:
        print(f"\n{'=' * 72}")
        print(f"  {example.name} ({example.actions} actions)")
        print(f"{'=' * 72}")

        ctx = run_example(example)

        try:
            results = run_checks(ctx)
            failures = print_results(example.name, results)
            total_pass += sum(1 for r in results if r.passed)
            total_fail += failures
        finally:
            cleanup(ctx)

    print(f"\n{'=' * 72}")
    print(f"  TOTAL: {total_pass} passed, {total_fail} failed")
    print(f"{'=' * 72}\n")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
