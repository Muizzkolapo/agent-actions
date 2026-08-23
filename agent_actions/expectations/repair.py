"""Composing the regeneration prompt for repair: auto."""

from __future__ import annotations

import json
from typing import Any

from agent_actions.expectations.types import SuiteResult

REPAIR_TEMPLATE = """{original_prompt}

## Your previous output failed validation

```json
{response_json}
```

## Failed expectations — the regenerated output must satisfy every one
{failed_lines}

## Passing expectations — the regenerated output must keep satisfying these
{passing_lines}

Regenerate the complete output, fixing every failed expectation while
preserving everything the passing expectations already verified."""


def compose_repair_prompt(
    original_prompt: str,
    response: dict[str, Any],
    suite_result: SuiteResult,
    hints: dict[str, str],
) -> str:
    """One instruction from the full failure list, naming what must be preserved."""
    failed_lines = "\n".join(
        f"- {o.id}"
        + (f" [{o.severity}]" if o.severity != "fail" else "")
        + (f": {o.detail}" if o.detail else "")
        + (f" (hint: {hints[o.id]})" if o.id in hints else "")
        for o in suite_result.outcomes
        if not o.passed
    )
    passing = [o.id for o in suite_result.outcomes if o.passed]
    passing_lines = "\n".join(f"- {oid}" for oid in passing) if passing else "(none yet)"
    return REPAIR_TEMPLATE.format(
        original_prompt=original_prompt,
        response_json=json.dumps(response, default=str),
        failed_lines=failed_lines or "(none)",
        passing_lines=passing_lines,
    )
