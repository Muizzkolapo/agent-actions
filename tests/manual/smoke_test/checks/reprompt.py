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
        results: list[CheckResult] = []

        if ctx.exit_code != 0:
            results.append(
                CheckResult(
                    False,
                    f"reprompt({self.action}): pipeline completed",
                    f"exit code {ctx.exit_code} — cannot verify reprompt",
                )
            )
            return results

        events_path = ctx.target_dir / "events.json"
        if not events_path.exists():
            results.append(
                CheckResult(
                    False,
                    f"reprompt({self.action}): events.json exists",
                    "events.json not found",
                )
            )
            return results

        # Parse NDJSON events
        events: list[dict] = []
        try:
            for line in events_path.read_text().splitlines():
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            results.append(
                CheckResult(
                    False,
                    f"reprompt({self.action}): events parseable",
                    f"failed to parse events.json: {e}",
                )
            )
            return results

        # Look for validation events related to this action.
        # Evidence comes in two forms:
        # 1. DataValidationStartedEvent with message containing "RepromptValidation"
        # 2. LogEvent with message like "[action=classify_genre] Validation passed on attempt 1/2"
        # The action name may appear in the message field, not in data.action_name
        validation_events = []
        for event in events:
            event_type = event.get("event_type", "")
            message = event.get("message", "")

            # Match events mentioning this action (including versioned: action_1, action_2)
            if self.action not in message:
                continue

            if event_type in ("DataValidationStartedEvent", "DataValidationPassedEvent"):
                validation_events.append(event)
            elif "Validation" in message or "attempt" in message:
                validation_events.append(event)

        if validation_events:
            results.append(
                CheckResult(
                    True,
                    f"reprompt({self.action}): validation ran",
                    f"{len(validation_events)} validation events found",
                )
            )
        else:
            results.append(
                CheckResult(
                    False,
                    f"reprompt({self.action}): validation ran",
                    f"no validation events for '{self.action}' in events.json",
                )
            )

        return results
