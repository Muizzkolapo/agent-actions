"""Parsing and evaluating an ``expression`` expectation's condition.

Reuses the guard machinery's own grammar and AST so a condition string is
portable between a ``guard:`` block and an ``expect:`` entry unchanged.
"""

from __future__ import annotations

from typing import Any

from agent_actions.input.preprocessing.parsing.ast_nodes import WhereClauseAST


class ExpressionParseError(ValueError):
    """Raised when a condition cannot be used: bad syntax, blocklist, or udf: prefix."""


def parse_condition(condition: str) -> WhereClauseAST:
    """Parse a condition through the guard blocklist and grammar; expressions never take udf:."""
    raise NotImplementedError


def referenced_field_paths(node: Any) -> list[str]:
    """Every field path a condition reads, in first-appearance order."""
    raise NotImplementedError


def evaluate_condition(condition: str, record: dict[str, Any]) -> tuple[bool, str]:
    """Evaluate a condition against one record; a missing field is a failure, not an error."""
    raise NotImplementedError


def _expression_unreachable(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    raise NotImplementedError(
        "expression is dispatched by the runner against the whole record, not registry.check"
    )
