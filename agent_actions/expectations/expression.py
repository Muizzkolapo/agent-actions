"""Parsing and evaluating an ``expression`` expectation's condition.

Reuses the guard machinery's own grammar and AST so a condition string is
portable between a ``guard:`` block and an ``expect:`` entry unchanged.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from agent_actions.errors import ValidationError
from agent_actions.guards.guard_parser import GuardParser, GuardType
from agent_actions.input.preprocessing.parsing.ast_nodes import (
    ASTNode,
    ComparisonNode,
    FieldNode,
    FunctionNode,
    GuardSemanticError,
    LogicalNode,
    MissingFieldError,
    WhereClauseAST,
)
from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser
from agent_actions.utils.dict import get_nested_value


class ExpressionParseError(ValueError):
    """Raised when a condition cannot be used: bad syntax, blocklist, or udf: prefix."""


_parser = WhereClauseParser()


@lru_cache(maxsize=256)
def parse_condition(condition: str) -> WhereClauseAST:
    """Parse a condition through the guard blocklist and grammar; expressions never take udf:."""
    try:
        guard_expression = GuardParser.parse(condition)
    except ValidationError as exc:
        raise ExpressionParseError(str(exc)) from exc
    if guard_expression.type is GuardType.UDF:
        raise ExpressionParseError(
            "udf: conditions are not supported in expression expectations; "
            "register an @expectation_check function instead"
        )
    result = _parser.parse(condition)
    if not result.success or result.ast is None:
        message = result.error.message if result.error else "unparseable condition"
        raise ExpressionParseError(f"condition {condition!r} does not parse: {message}")
    return result.ast


def referenced_field_paths(node: ASTNode | None) -> list[str]:
    """Every field path a condition reads, in first-appearance order."""
    found: list[str] = []

    def walk(n: ASTNode | None) -> None:
        if n is None:
            return
        if isinstance(n, FieldNode):
            if n.field_path not in found:
                found.append(n.field_path)
        elif isinstance(n, (ComparisonNode, LogicalNode)):
            walk(n.left)
            walk(n.right)
        elif isinstance(n, FunctionNode):
            for argument in n.arguments:
                walk(argument)

    walk(node)
    return found


def evaluate_condition(condition: str, record: dict[str, Any]) -> tuple[bool, str]:
    """Evaluate a condition against one record; a missing field is a failure, not an error."""
    ast = parse_condition(condition)
    try:
        passed = bool(ast.evaluate(record))
    except (MissingFieldError, GuardSemanticError) as exc:
        return False, str(exc)
    if passed:
        return True, ""
    values = ", ".join(
        f"{path}={get_nested_value(record, path)!r}" for path in referenced_field_paths(ast.root)
    )
    return False, f"condition {condition!r} is false ({values})"


def _expression_unreachable(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    raise NotImplementedError(
        "expression is dispatched by the runner against the whole record, not registry.check"
    )
