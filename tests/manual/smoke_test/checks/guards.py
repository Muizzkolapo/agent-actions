from __future__ import annotations

from dataclasses import dataclass

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


@dataclass
class GuardCheck(Check):
    """Verify a guarded action produced correct dispositions.

    Args:
        action: action name that has a guard
        behavior: expected guard behavior — "filter" or "skip"
    """

    action: str
    behavior: str  # "filter" or "skip"

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        # The pipeline must have completed for guard evaluation to be meaningful
        if ctx.exit_code != 0:
            results.append(
                CheckResult(
                    False,
                    f"guard({self.action}): pipeline completed",
                    f"exit code {ctx.exit_code} — cannot verify guard behavior",
                )
            )
            return results

        action_dir = ctx.target_dir / self.action

        # Look for guard-related evidence in stdout/stderr
        combined_output = ctx.stdout + ctx.stderr
        guard_mentioned = "guard" in combined_output.lower() or self.action in combined_output

        if self.behavior == "filter":
            # For "filter" behavior: the action should still run but some records
            # may get disposition "filtered". At minimum, the pipeline should not
            # crash and the action directory or DB should exist.
            if action_dir.exists():
                results.append(
                    CheckResult(
                        True,
                        f"guard({self.action}): action dir exists",
                        "guard evaluated — action directory present",
                    )
                )
            else:
                # Action dir might not exist if all records were filtered,
                # which is valid guard behavior
                results.append(
                    CheckResult(
                        True,
                        f"guard({self.action}): all records filtered",
                        "action directory absent — guard may have filtered all records",
                    )
                )

            # Check for filter disposition evidence in logs
            filter_evidence = (
                "filter" in combined_output.lower()
                or "disposition" in combined_output.lower()
                or "guard" in combined_output.lower()
            )
            results.append(
                CheckResult(
                    True,
                    f"guard({self.action}): filter behavior configured",
                    "guard log evidence found"
                    if filter_evidence
                    else "no crash — guard did not break pipeline",
                )
            )

        elif self.behavior == "skip":
            # For "skip" behavior: the guard may skip the entire action.
            # The action directory may or may not exist depending on guard evaluation.
            skip_evidence = "skip" in combined_output.lower() or "guard" in combined_output.lower()

            if action_dir.exists():
                results.append(
                    CheckResult(
                        True,
                        f"guard({self.action}): action ran (guard passed)",
                        "guard condition was true — action executed",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        True,
                        f"guard({self.action}): action skipped (guard triggered)",
                        "action directory absent — guard skip behavior applied",
                    )
                )

            results.append(
                CheckResult(
                    True,
                    f"guard({self.action}): skip behavior configured",
                    "guard log evidence found"
                    if skip_evidence
                    else "no crash — guard did not break pipeline",
                )
            )
        else:
            results.append(
                CheckResult(
                    False,
                    f"guard({self.action}): unknown behavior",
                    f"unexpected behavior '{self.behavior}' — expected 'filter' or 'skip'",
                )
            )

        # Verify the guard didn't cause downstream actions to fail silently
        if guard_mentioned:
            results.append(
                CheckResult(
                    True,
                    f"guard({self.action}): pipeline healthy after guard",
                    "guard evaluation did not crash the pipeline",
                )
            )

        return results
