"""Flag UDF reads of `data.get("X")` / `data["X"]` where X is not a bus namespace."""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any

from agent_actions.record.envelope import RECORD_FRAMEWORK_FIELDS
from agent_actions.utils.constants import RUNTIME_BUS_NAMESPACES


def _bus_key(node: ast.AST) -> str | None:
    """Return the literal key of a `data.get("X")` / `data["X"]` read, else None."""
    # data.get("literal")
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "data"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    # data["literal"]
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "data"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    ):
        return node.slice.value
    return None


class _BusKeyCollector(ast.NodeVisitor):
    """Collect (enclosing-function, literal bus key) pairs; innermost function wins."""

    def __init__(self, fallback: str) -> None:
        self._fallback = fallback
        self._func_stack: list[str] = []
        self.reads: list[tuple[str, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _record(self, node: ast.AST) -> None:
        key = _bus_key(node)
        if key is not None:
            owner = self._func_stack[-1] if self._func_stack else self._fallback
            self.reads.append((owner, key))

    def visit_Call(self, node: ast.Call) -> None:
        self._record(node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self._record(node)
        self.generic_visit(node)


def find_unknown_bus_namespaces(sources: dict[str, str], valid_namespaces: set[str]) -> list[str]:
    """Return one warning per literal bus key that is not a valid namespace.

    Findings are attributed to the enclosing UDF, so a source file holding several
    UDFs never cross-attributes; a `sources` key is only the fallback label for a
    read outside any function. Non-literal keys (`data.get(var)`) are skipped.
    """
    findings: list[str] = []
    for label, src in sources.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        collector = _BusKeyCollector(label)
        collector.visit(tree)
        # Dedup per source only: the same (owner, key) in two different sources are
        # genuinely distinct findings (e.g. an identically-named nested helper in two
        # UDFs), and must not collapse into one.
        seen: set[tuple[str, str]] = set()
        for owner, key in collector.reads:
            if key in valid_namespaces or (owner, key) in seen:
                continue
            seen.add((owner, key))
            findings.append(
                f"{owner}: reads bus namespace '{key}' which is not an action name "
                f"in the workflow. The bus is keyed by action name — check for an "
                f"impl-name/action-name mismatch (a wrong key reads an empty dict silently)."
            )
    return findings


def udf_sources(registry: dict, refs: set[str]) -> dict[str, str]:
    """Each referenced UDF's own function body, keyed by the name that referenced it."""
    sources: dict[str, str] = {}
    for ref in refs:
        meta = registry.get(ref) or registry.get(ref.lower())
        if meta is None:
            continue
        try:
            sources[ref] = textwrap.dedent(inspect.getsource(meta["function"]))
        except (OSError, TypeError, KeyError):
            continue
    return sources


def promoted_version_names(config: Any) -> set[str]:
    """Every name a versioned action's guard context promotes to the top level.

    Finds the contexts; `VersionNamespaceBuilder.promoted_names` decides what each one
    promotes, so a context cannot be read differently here than where it is built (#1199).
    A union across the whole config: a name promoted by one action's context is allowed
    for every action, the same over-approximation `guard_valid_namespaces` carries (#1192).
    """
    from agent_actions.prompt.context.scope_builder import VersionNamespaceBuilder

    names: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            vc = obj.get("_version_context")
            if isinstance(vc, dict):
                names.update(VersionNamespaceBuilder.promoted_names(vc))
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(config)
    return names


def guard_valid_namespaces(action_names: set[str], loop_params: set[str] | None = None) -> set[str]:
    """What a guard UDF may read: the union over every shape its context can take.

    A guard receives the evaluation context rather than the action bus: a first-stage
    action's carries the record's envelope, a versioned one's the promoted loop keys.
    The scan does not know which action a guard belongs to, so it allows all of them,
    and a guard on a later action reading ``source_guid`` goes unreported; narrowing
    that needs the per-action derivation ``build_guard_context`` performs (#1192).
    """
    return (
        action_names
        | RUNTIME_BUS_NAMESPACES
        | (RECORD_FRAMEWORK_FIELDS - {"content"})
        | (loop_params or set())
    )


def bus_namespace_warnings(
    registry: dict,
    impl_refs: set[str],
    guard_refs: set[str],
    action_names: set[str],
    loop_params: set[str] | None = None,
) -> list[str]:
    """Reads of an unknown bus namespace by each referenced tool and guard UDF.

    Each UDF's own body is scanned, not its file: a shared tools/ dir holds UDFs for many
    workflows, and helpers often receive a plain record rather than the bus. Guards are
    scanned against their wider set apart from tools, which merging would widen too.
    """
    return find_unknown_bus_namespaces(
        udf_sources(registry, impl_refs), action_names | RUNTIME_BUS_NAMESPACES
    ) + find_unknown_bus_namespaces(
        udf_sources(registry, guard_refs), guard_valid_namespaces(action_names, loop_params)
    )
