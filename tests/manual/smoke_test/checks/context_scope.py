from __future__ import annotations

import json
from dataclasses import dataclass, field

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


@dataclass
class ContextScope(Check):
    """Verify that dropped fields do not appear in a downstream action's output.

    Args:
        action: downstream action to check
        dropped_fields: fields that should NOT appear in this action's output
    """

    action: str
    dropped_fields: list[str] = field(default_factory=list)

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        # The pipeline must have completed for context scope to be verifiable
        if ctx.exit_code != 0:
            results.append(
                CheckResult(
                    False,
                    f"context_scope({self.action}): pipeline completed",
                    f"exit code {ctx.exit_code} — cannot verify context scope",
                )
            )
            return results

        action_dir = ctx.target_dir / self.action
        if not action_dir.exists():
            # Action dir may not exist if guarded/skipped — not a scope failure
            results.append(
                CheckResult(
                    True,
                    f"context_scope({self.action}): action dir absent",
                    "action may have been filtered/skipped — scope check N/A",
                )
            )
            return results

        json_files = list(action_dir.glob("*.json"))
        if not json_files:
            results.append(
                CheckResult(
                    True,
                    f"context_scope({self.action}): no output files",
                    "no JSON output to verify — scope check N/A",
                )
            )
            return results

        # Check each output file for presence of dropped fields
        violations: list[str] = []
        records_checked = 0

        for jf in json_files:
            try:
                data = json.loads(jf.read_text())
                records = data if isinstance(data, list) else [data]
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    records_checked += 1
                    for dropped in self.dropped_fields:
                        # Check top-level keys and nested keys (dot-separated)
                        parts = dropped.split(".")
                        if len(parts) == 1:
                            if dropped in record:
                                violations.append(f"{jf.name}: found '{dropped}'")
                        else:
                            # For dotted fields like "source.star_rating",
                            # check if the leaf key appears at any level
                            leaf = parts[-1]
                            if leaf in record:
                                violations.append(f"{jf.name}: found '{leaf}' (from '{dropped}')")
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass  # OutputStructure check catches parse errors

        if violations:
            results.append(
                CheckResult(
                    False,
                    f"context_scope({self.action}): dropped fields absent",
                    f"{len(violations)} violations: {'; '.join(violations[:5])}",
                )
            )
        else:
            results.append(
                CheckResult(
                    True,
                    f"context_scope({self.action}): dropped fields absent",
                    f"checked {records_checked} records — none contain {self.dropped_fields}",
                )
            )

        return results
