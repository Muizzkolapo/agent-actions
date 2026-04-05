from __future__ import annotations

from tests.manual.smoke_test.context import CheckResult, RunContext


def run_checks(ctx: RunContext) -> list[CheckResult]:
    """Run all checks registered on this example and return results."""
    results: list[CheckResult] = []
    for check in ctx.example.checks:
        results.extend(check.verify(ctx))
    return results


def print_results(example_name: str, results: list[CheckResult]) -> int:
    """Print results for one example. Return number of failures."""
    failures = 0
    for r in results:
        status = "\033[32mPASS\033[0m" if r.passed else "\033[31mFAIL\033[0m"
        detail = f"  ({r.message})" if r.message else ""
        print(f"  {status}  {r.name}{detail}")
        if not r.passed:
            failures += 1
    return failures
