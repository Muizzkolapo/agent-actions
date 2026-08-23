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


def _one_line(text: str) -> str:
    return " ".join(text.split())


def compose_repair_prompt(
    original_prompt: str,
    response: Any,
    suite_result: SuiteResult,
    hints: dict[str, str],
) -> str:
    """One instruction from the full failure list, naming what must be preserved.

    Skipped outcomes are omitted: a rule the judge budget left unevaluated says
    nothing the regeneration can act on.
    """
    failed_lines = "\n".join(
        f"- {o.id}"
        + (f" [{o.severity}]" if o.severity != "error" else "")
        + (f": {_one_line(o.detail)}" if o.detail else "")
        + (f" (hint: {_one_line(hints[o.id])})" if o.id in hints else "")
        for o in suite_result.outcomes
        if not o.passed and not o.skipped
    )
    # Skipped outcomes say nothing either way: one that failed was never
    # evaluated, one that passed was waived, and neither is something the
    # regenerated output can be asked to preserve.
    passing = [o.id for o in suite_result.outcomes if o.passed and not o.skipped]
    passing_lines = "\n".join(f"- {oid}" for oid in passing) if passing else "(none yet)"
    return REPAIR_TEMPLATE.format(
        original_prompt=original_prompt,
        response_json=json.dumps(response, default=str),
        failed_lines=failed_lines or "(none)",
        passing_lines=passing_lines,
    )
