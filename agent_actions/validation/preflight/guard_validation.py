"""Static validation for action ``guard`` clauses.

Outside ``workflow.coordinator`` so ``PreflightService`` can import
it without dragging in the runtime stack via a circular import."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_actions.guards.bare_reference import (
    bare_reference_is_unresolvable,
    spreads_output_flat,
)
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


def _collect_field_nodes(node: ASTNode) -> list[str]:
    """Every field path the clause reads, from both sides of every comparison."""
    from agent_actions.input.preprocessing.parsing.ast_nodes import FieldNode

    paths: list[str] = []
    for comparison in _find_comparison_nodes(node):
        for side in (comparison.left, comparison.right):
            if isinstance(side, FieldNode):
                paths.append(side.field_path)
    return paths


def _version_params(config: dict) -> list[str]:
    versions = config.get("versions")
    if isinstance(versions, dict):
        versions = [versions]
    if not isinstance(versions, list):
        return []
    return [v["param"] for v in versions if isinstance(v, dict) and v.get("param")]


def _suggest_dotted(variable: str, upstreams: list[str]) -> str:
    """Name the spelling that would resolve, the way the runtime's own error does."""
    if len(upstreams) == 1:
        return f" Did you mean '{upstreams[0]}.{variable}'?"
    if upstreams:
        options = ", ".join(f"'{name}.{variable}'" for name in sorted(upstreams)[:3])
        return f" Did you mean one of {options}?"
    return ""


def _check_bare_field_references(
    ast_root: ASTNode, clause: str, action_name: str, config: dict, action_configs: dict
) -> list[str]:
    """Refuse a clause naming a field without its namespace, which filters every record.

    The runtime does detect this -- per record, at warning level, after the record is
    already filtered -- so a run discards an entire input and still exits successfully.
    Only a reference `bare_reference_is_unresolvable` can prove wrong is refused; a bare
    name resolves through several promotions and refusing all of them would reject
    configurations that work.
    """
    upstreams = [d for d in config.get("dependencies") or [] if isinstance(d, str)]
    output_fields = {
        name: (action_configs[name].get("output_field") if name in action_configs else None)
        for name in upstreams
    }
    known = {name: name in action_configs for name in upstreams}
    output_fields = {k: v for k, v in output_fields.items() if known[k]}
    spreads_flat = any(
        spreads_output_flat(action_configs[name]) for name in upstreams if name in action_configs
    )

    errors: list[str] = []
    for variable in _collect_field_nodes(ast_root):
        if not bare_reference_is_unresolvable(
            variable,
            upstreams=upstreams,
            upstream_output_fields=output_fields,
            version_params=_version_params(config),
            any_upstream_spreads_flat=spreads_flat,
        ):
            continue
        errors.append(
            f"Action '{action_name}': guard condition '{clause}' references field "
            f"'{variable}' without an action prefix. Content is namespaced, so this "
            f"resolves against nothing and every record is filtered at runtime."
            f"{_suggest_dotted(variable, upstreams)}"
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
            errors.extend(
                _check_bare_field_references(
                    parse_result.ast.root, clause, action_name, config, action_configs
                )
            )

    return errors


__all__ = ["validate_guard_conditions"]
