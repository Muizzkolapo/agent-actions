from __future__ import annotations

import json
from dataclasses import dataclass

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


@dataclass
class RepromptCheck(Check):
    """Verify a reprompt-enabled action triggered retries.

    Parses events.json (NDJSON) for retry/reprompt evidence. If the action
    is configured for reprompt, there MUST be retry evidence -- no excuses.

    Args:
        action: action name with reprompt configured
    """

    action: str

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        # The pipeline must have completed for reprompt to be verifiable
        if ctx.exit_code != 0:
            results.append(
                CheckResult(
                    False,
                    f"reprompt({self.action}): pipeline completed",
                    f"exit code {ctx.exit_code} -- cannot verify reprompt",
                )
            )
            return results

        # Parse events.json (NDJSON format) for retry evidence
        events_path = ctx.target_dir / "events.json"
        if not events_path.exists():
            results.append(
                CheckResult(
                    False,
                    f"reprompt({self.action}): events.json exists",
                    "events.json not found -- cannot verify reprompt",
                )
            )
            return results

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

        # Look for events related to this action that indicate retries
        retry_events = []
        for event in events:
            event_data = event.get("data", {})
            event_action = event_data.get("action_name", "")
            event_type = event.get("event_type", "")

            # Match events for this action
            if event_action != self.action:
                continue

            # Check for attempt > 1 or reprompt-related event types
            attempt = event_data.get("attempt", 0)
            if attempt > 1:
                retry_events.append(event)
            elif "Reprompt" in event_type or "Retry" in event_type:
                retry_events.append(event)

        if retry_events:
            results.append(
                CheckResult(
                    True,
                    f"reprompt({self.action}): retry evidence found",
                    f"{len(retry_events)} retry-related events",
                )
            )
        else:
            results.append(
                CheckResult(
                    False,
                    f"reprompt({self.action}): retry evidence found",
                    "no retry attempts found in events.json",
                )
            )

        return results
