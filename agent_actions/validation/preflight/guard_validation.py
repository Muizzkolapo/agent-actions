"""Static validation for action ``guard`` clauses.

Outside ``workflow.coordinator`` so ``PreflightService`` can import
it without dragging in the runtime stack via a circular import."""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

from agent_actions.guards.bare_reference import (
    bare_reference_is_unresolvable,
    spreads_output_flat,
)
from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser
from agent_actions.prompt.context.scope_builder import VersionNamespaceBuilder
from agent_actions.utils.constants import RESERVED_NAMES_NO_RECORD_HAS
from agent_actions.validation.static_analyzer.errors import read_through_reserved_name

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
    """Every field path the clause reads, anywhere in the tree.

    Not scoped to comparison operands: a bare field or a bare function call is a
    complete guard clause on its own (``clause: "name"``, ``clause: "LENGTH(name)"``),
    with no comparison for a comparison-scoped walk to find. An unnamespaced field
    there resolves against nothing and filters every record exactly as one beside
    ``==`` does, so it needs the same check.
    """
    from agent_actions.input.preprocessing.parsing.ast_nodes import (
        ComparisonNode,
        FieldNode,
        FunctionNode,
        LogicalNode,
    )

    paths: list[str] = []

    def walk(operand: ASTNode | None) -> None:
        if operand is None:
            return
        if isinstance(operand, FieldNode):
            paths.append(operand.field_path)
        elif isinstance(operand, FunctionNode):
            for argument in operand.arguments:
                walk(argument)
        elif isinstance(operand, ComparisonNode):
            walk(operand.left)
            walk(operand.right)
        elif isinstance(operand, LogicalNode):
            walk(operand.left)
            walk(operand.right)

    walk(node)
    return paths


def _check_function_calls(ast_root: ASTNode, clause: str, action_name: str) -> list[str]:
    """Refuse a guard calling an unregistered function, or the wrong number of arguments.

    Both are deterministic -- every record would fail evaluation identically -- so this
    catches them before any record is read, instead of at the first one `evaluate_node`
    raises on. A wrong arity is detected by calling the real function with placeholder
    values of the written argument count: every builtin validates count before it looks
    at a value, so this needs no per-function arity table to drift out of sync.
    """
    from agent_actions.input.preprocessing.parsing.ast_nodes import (
        ComparisonNode,
        FunctionNode,
        LogicalNode,
    )
    from agent_actions.input.preprocessing.parsing.operators import FUNCTIONS

    errors: list[str] = []

    def walk(node: ASTNode | None) -> None:
        if node is None:
            return
        if isinstance(node, FunctionNode):
            if node.function_name not in FUNCTIONS:
                errors.append(
                    f"Action '{action_name}': guard condition '{clause}' calls "
                    f"'{node.function_name}', which is not a registered function. "
                    f"Available: {', '.join(sorted(FUNCTIONS))}."
                )
            else:
                try:
                    FUNCTIONS[node.function_name](["x"] * len(node.arguments))
                except ValueError as e:
                    errors.append(
                        f"Action '{action_name}': guard condition '{clause}' calls "
                        f"'{node.function_name}' with {len(node.arguments)} argument(s): {e}"
                    )
            for argument in node.arguments:
                walk(argument)
        elif isinstance(node, ComparisonNode):
            walk(node.left)
            walk(node.right)
        elif isinstance(node, LogicalNode):
            walk(node.left)
            walk(node.right)

    walk(ast_root)
    return errors


def _check_reserved_name_reads(
    ast_root: ASTNode, clause: str, action_name: str, action_names: Collection[str]
) -> list[str]:
    """Refuse a clause reading through `action`, `prompt` or `schema`.

    No record carries those names, so the field is missing on every record and every
    record is filtered while the run reports success.
    """
    errors: list[str] = []
    for path in dict.fromkeys(_collect_field_nodes(ast_root)):
        name, _, rest = path.partition(".")
        if not rest or name not in RESERVED_NAMES_NO_RECORD_HAS:
            continue
        problem, fix = read_through_reserved_name(name, path, rest, action_names)
        errors.append(
            f"Action '{action_name}': guard condition '{clause}' {problem}, so every "
            f"record would be filtered. {fix}"
        )
    return errors


def _version_params(config: dict) -> list[str]:
    """The version names a guard clause may use bare, read from the expanded config.

    This runs after expansion, which replaces `versions` with a per-variant
    `_version_context` -- so reading `versions` found nothing and every guard naming a
    version param was refused as unresolvable.
    """
    version_context = config.get("_version_context")
    if not isinstance(version_context, dict):
        return []
    return sorted(VersionNamespaceBuilder.promoted_names(version_context))


def _suggest_dotted(variable: str, upstreams: list[str]) -> str:
    """Name the spelling that would resolve, the way the runtime's own error does."""
    if len(upstreams) == 1:
        return f" Did you mean '{upstreams[0]}.{variable}'?"
    if upstreams:
        options = ", ".join(f"'{name}.{variable}'" for name in sorted(upstreams)[:3])
        return f" Did you mean one of {options}?"
    return f" A first action reads its staged row under 'source'. Did you mean 'source.{variable}'?"


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
    for variable in dict.fromkeys(_collect_field_nodes(ast_root)):
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
            errors.extend(_check_function_calls(parse_result.ast.root, clause, action_name))
            errors.extend(
                _check_reserved_name_reads(
                    parse_result.ast.root, clause, action_name, action_configs
                )
            )
            errors.extend(
                _check_bare_field_references(
                    parse_result.ast.root, clause, action_name, config, action_configs
                )
            )

    return errors


__all__ = ["validate_guard_conditions"]
