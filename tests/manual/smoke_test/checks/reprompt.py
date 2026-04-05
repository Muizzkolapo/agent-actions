from __future__ import annotations

import json
from dataclasses import dataclass

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


@dataclass
class RepromptCheck(Check):
    """Verify a reprompt-enabled action ran validation.

    Parses events.json (NDJSON) for DataValidationStartedEvent or
    LogEvent messages mentioning the action and validation/reprompt.

    Args:
        action: action name with reprompt configured
    """

    action: str

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        if ctx.exit_code != 0:
            return [
                CheckResult(
                    False,
                    f"reprompt({self.action}): pipeline completed",
                    f"exit code {ctx.exit_code} — cannot verify reprompt",
                )
            ]

        events_path = ctx.target_dir / "events.json"
        if not events_path.exists():
            return [
                CheckResult(
                    False,
                    f"reprompt({self.action}): events.json exists",
                    "events.json not found",
                )
            ]

        # Single-pass: stream lines, parse only relevant ones
        validation_count = 0
        try:
            with events_path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Quick string check before parsing JSON
                    if self.action not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    event_type = event.get("event_type", "")
                    message = event.get("message", "")
                    if self.action not in message:
                        continue
                    if event_type in ("DataValidationStartedEvent", "DataValidationPassedEvent"):
                        validation_count += 1
                    elif "Validation" in message or "attempt" in message:
                        validation_count += 1
        except OSError:
            return [
                CheckResult(
                    False,
                    f"reprompt({self.action}): events readable",
                    "failed to read events.json",
                )
            ]

        return [
            CheckResult(
                passed=validation_count > 0,
                name=f"reprompt({self.action}): validation ran",
                message=f"{validation_count} validation events found"
                if validation_count > 0
                else f"no validation events for '{self.action}' in events.json",
            )
        ]
