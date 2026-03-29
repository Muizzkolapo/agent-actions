"""Reusable harness for doc-vs-code audit tests.

Each audit module creates a ``DocAudit`` instance, registers tests via
``run_test`` / ``run_gap``, and returns the instance for aggregation.

Categories:
  PASS — doc promise is delivered by the code
  FAIL — doc promise is NOT delivered (bug or regression)
  GAP  — feature is documented but implementation is missing entirely
"""

from __future__ import annotations

import sys
import traceback


class DocAudit:
    """Accumulates results for a single audit module."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self.passed = 0
        self.failed = 0
        self.gaps = 0
        self.errors: list[tuple[str, str]] = []  # (test_name, category)

    # ------------------------------------------------------------------
    # Test runners
    # ------------------------------------------------------------------

    def run_test(self, name: str, fn) -> None:
        """Run *fn*; PASS on success, FAIL on exception."""
        try:
            fn()
            self.passed += 1
            print(f"  \033[32mPASS\033[0m  {name}")
        except Exception:
            self.failed += 1
            self.errors.append((name, "FAIL"))
            print(f"  \033[31mFAIL\033[0m  {name}")
            traceback.print_exc(file=sys.stdout)
            print()

    def run_gap(self, name: str, fn) -> None:
        """Run *fn*; PASS if the feature exists, GAP if missing."""
        try:
            fn()
            self.passed += 1
            print(f"  \033[32mPASS\033[0m  {name}")
        except Exception:
            self.gaps += 1
            self.errors.append((name, "GAP"))
            print(f"  \033[33m GAP\033[0m  {name}")
            traceback.print_exc(file=sys.stdout)
            print()

    def section(self, title: str) -> None:
        print(f"\n{'=' * 72}")
        print(f"  {title}")
        print(f"{'=' * 72}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.gaps

    def summary(self) -> int:
        """Print results and return exit code (0 = no failures)."""
        print(f"\n{'=' * 72}")
        print(
            f"  RESULTS: {self.passed} passed, {self.failed} failed, {self.gaps} gaps  (total: {self.total})"
        )
        if self.errors:
            print()
            for name, category in self.errors:
                color = "\033[31m" if category == "FAIL" else "\033[33m"
                print(f"  {color}{category}\033[0m  {name}")
        print(f"{'=' * 72}\n")
        return 0 if self.failed == 0 else 1


def aggregate_summary(audits: list[tuple[str, DocAudit]]) -> int:
    """Print a combined summary table for multiple audit modules."""
    total_pass = sum(a.passed for _, a in audits)
    total_fail = sum(a.failed for _, a in audits)
    total_gap = sum(a.gaps for _, a in audits)
    total = total_pass + total_fail + total_gap

    print(f"\n{'=' * 72}")
    print("  AGGREGATE RESULTS")
    print(f"{'=' * 72}")
    for module_name, audit in audits:
        status = "\033[32mOK\033[0m" if audit.failed == 0 else "\033[31mFAIL\033[0m"
        gap_str = f", {audit.gaps} gaps" if audit.gaps else ""
        print(f"  {status}  {module_name}: {audit.passed} passed, {audit.failed} failed{gap_str}")
    print(f"{'=' * 72}")
    print(f"  TOTAL: {total_pass} passed, {total_fail} failed, {total_gap} gaps  ({total} tests)")
    print(f"{'=' * 72}\n")

    return 0 if total_fail == 0 else 1
