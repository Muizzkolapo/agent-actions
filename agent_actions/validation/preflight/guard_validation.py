"""Static validation for action ``guard`` clauses.

Outside ``workflow.coordinator`` so ``PreflightService`` can import
it without dragging in the runtime stack via a circular import."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

if TYPE_CHECKING:
    from agent_actions.input.preprocessing.parsing.ast_nodes import (
        ASTNode,
        ComparisonNode,
    )


def _find_comparison_nodes(node: ASTNode) -> list[ComparisonNode]:
    from agent_actions.input.preprocessing.parsing.ast_nodes import (
        ComparisonNode,
        LogicalNode,
    )

    results: list[ComparisonNode] = []
    if isinstance(node, ComparisonNode):
        results.append(node)
    elif isinstance(node, LogicalNode):
        results.extend(_find_comparison_nodes(node.left))
        if node.right is not None:
            results.extend(_find_comparison_nodes(node.right))
    return results


def _check_bare_identifier_rhs(ast_root: ASTNode, clause: str, action_name: str) -> list[str]:
    """Flag comparisons whose RHS is a bare identifier (usually an unquoted string)."""
    from agent_actions.input.preprocessing.parsing.ast_nodes import FieldNode

    errors: list[str] = []
    for comparison in _find_comparison_nodes(ast_root):
        if comparison.right is not None and isinstance(comparison.right, FieldNode):
            field = comparison.right.field_path
            left_repr = (
                comparison.left.field_path if isinstance(comparison.left, FieldNode) else "..."
            )
            op = comparison.operator.value
            errors.append(
                f"Action '{action_name}': guard condition '{clause}' compares field "
                f"'{left_repr}' to bare identifier '{field}'. "
                f"If '{field}' is a string value, quote it: "
                f'{left_repr} {op} "{field}"'
            )
    return errors


def validate_guard_conditions(action_configs: dict) -> list[str]:
    """Parse all guard clauses, returning one error message per invalid one.

    Runs after config expansion (guard dicts use 'clause', not 'condition')."""
    errors: list[str] = []
    parser = WhereClauseParser()

    for action_name, config in action_configs.items():
        guard = config.get("guard")
        if not guard or not isinstance(guard, dict):
            continue
        clause = guard.get("clause")
        if not clause:
            continue

        parse_result = parser.parse_cached(clause)
        if not parse_result.success:
            error = parse_result.error
            detail = error.message if error else "parse failed"
            errors.append(f"Action '{action_name}': invalid guard condition '{clause}': {detail}")
            continue

        if parse_result.ast is not None:
            errors.extend(_check_bare_identifier_rhs(parse_result.ast.root, clause, action_name))

    return errors


__all__ = ["validate_guard_conditions"]
