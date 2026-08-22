"""Composing the regeneration prompt for repair: auto."""

from __future__ import annotations

from typing import Any

from agent_actions.expectations.types import SuiteResult


def compose_repair_prompt(
    original_prompt: str,
    response: dict[str, Any],
    suite_result: SuiteResult,
    hints: dict[str, str],
) -> str:
    """One instruction from the full failure list, naming what must be preserved."""
    raise NotImplementedError
