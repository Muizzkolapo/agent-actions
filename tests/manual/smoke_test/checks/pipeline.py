from __future__ import annotations

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


class PipelineCompleted(Check):
    """Verify the CLI completed without crashing."""

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        return [
            CheckResult(
                passed=ctx.exit_code == 0,
                name="pipeline completed",
                message=f"exit code {ctx.exit_code}" if ctx.exit_code != 0 else "exit code 0",
            )
        ]
