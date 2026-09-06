"""Composing the regeneration prompt for repair: auto."""

from __future__ import annotations

import json
import re
from typing import Any

from agent_actions.expectations.types import Outcome, SuiteResult

REPAIR_FEEDBACK_TEMPLATE = """## Your previous output failed validation

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


_RECORD_INDEX = re.compile(r"\[\d+\]$")


def _hint_for(outcome_id: str, hints: dict[str, str]) -> str | None:
    """The author's hint for an outcome, whose id may carry a record index.

    Only a trailing ``[n]`` is stripped, so a rule genuinely named
    ``latency[p99]`` keeps its own hint instead of borrowing ``latency``'s.
    """
    if outcome_id in hints:
        return hints[outcome_id]
    return hints.get(_RECORD_INDEX.sub("", outcome_id))


def _failed_line(outcome: Outcome, hint: str | None) -> str:
    """One bullet naming a failed rule, why it failed, and how to fix it."""
    line = f"- {outcome.id}"
    if outcome.severity != "error":
        line += f" [{outcome.severity}]"
    if outcome.detail:
        line += f": {_one_line(outcome.detail)}"
    if hint:
        line += f" (hint: {_one_line(hint)})"
    return line


REPAIR_PLACEHOLDERS = ("original_prompt", "response_json", "failed_lines", "passing_lines")


class RepairTemplateError(ValueError):
    """An authored repair template names something the framework cannot supply."""


def check_repair_template(template: Any) -> None:
    """Refuse a template the composer could not fill, naming what it may use.

    Checked once at construction rather than per failure, so a typo is a config
    error rather than a regeneration that silently loses its feedback.
    """
    if not isinstance(template, str):
        raise RepairTemplateError(
            f"repair prompt must be a string, found {type(template).__name__}"
        )
    known = ", ".join(f"{{{name}}}" for name in REPAIR_PLACEHOLDERS)
    try:
        template.format(**dict.fromkeys(REPAIR_PLACEHOLDERS, ""))
    except KeyError as exc:
        raise RepairTemplateError(
            f"repair prompt names unknown placeholder {exc.args[0]!r}; it may use {known}"
        ) from exc
    except (IndexError, ValueError) as exc:
        raise RepairTemplateError(
            f"repair prompt is not a valid template ({exc}); it may use {known}"
        ) from exc


def render_repair_template(
    template: str,
    original_prompt: str,
    response: Any,
    suite_result: SuiteResult,
    hints: dict[str, str],
) -> str:
    """The author's template, filled with the payload ``auto`` would have composed."""
    return template.format(
        original_prompt=original_prompt,
        response_json=json.dumps(response, default=str),
        failed_lines=_failed_lines(suite_result, hints),
        passing_lines=_passing_lines(suite_result),
    )


def _failed_lines(suite_result: SuiteResult, hints: dict[str, str]) -> str:
    lines = "\n".join(
        _failed_line(o, _hint_for(o.id, hints))
        for o in suite_result.outcomes
        if not o.passed and not o.skipped
    )
    return lines or "(none)"


def _passing_lines(suite_result: SuiteResult) -> str:
    passing = [o.id for o in suite_result.outcomes if o.passed and not o.skipped]
    return "\n".join(f"- {oid}" for oid in passing) if passing else "(none yet)"


def compose_repair_prompt(
    original_prompt: str,
    response: Any,
    suite_result: SuiteResult,
    hints: dict[str, str],
) -> str:
    """The original prompt followed by what the regeneration must fix and keep."""
    return f"{original_prompt}\n\n{compose_repair_feedback(response, suite_result, hints)}"


def compose_repair_feedback(
    response: Any,
    suite_result: SuiteResult,
    hints: dict[str, str],
) -> str:
    """The failure list on its own, for a path that appends to the prompt it already sent.

    Skipped outcomes are omitted: a rule the judge budget left unevaluated says
    nothing the regeneration can act on.
    """
    # Skipped outcomes say nothing either way: one that failed was never
    # evaluated, one that passed was waived, and neither is something the
    # regenerated output can be asked to preserve.
    return REPAIR_FEEDBACK_TEMPLATE.format(
        response_json=json.dumps(response, default=str),
        failed_lines=_failed_lines(suite_result, hints),
        passing_lines=_passing_lines(suite_result),
    )
