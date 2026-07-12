"""Flag FILE-granularity UDFs that return freshly-built dicts without FileUDFResult."""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Callable, Iterator
from typing import Any

from agent_actions.config.types import Granularity
from agent_actions.utils.udf_management.registry import FileUDFResult


def _returns_fileudfresult(annotation: Any) -> bool:
    # Text-match by design: never imports or resolves the annotation (that can
    # raise); covers the class, string forward-refs, and Optional/Union wrappers.
    if annotation is FileUDFResult:
        return True
    if isinstance(annotation, str):
        return "FileUDFResult" in annotation
    return "FileUDFResult" in str(annotation)


def _is_dict_construct(node: ast.AST, dict_vars: set[str]) -> bool:
    """A freshly-built dict: a dict literal/comprehension, dict(...), or a name bound to one."""
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        return True
    return isinstance(node, ast.Name) and node.id in dict_vars


def _is_list_of_dicts(node: ast.AST, dict_vars: set[str]) -> bool:
    """A list literal or comprehension whose elements are freshly-built dicts."""
    if isinstance(node, ast.List):
        return any(_is_dict_construct(elt, dict_vars) for elt in node.elts)
    if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
        return _is_dict_construct(node.elt, dict_vars)
    return False


def _feeds_dicts(node: ast.AST, dict_vars: set[str], list_dict_vars: set[str]) -> bool:
    """A value that is, or aliases, a list of freshly-built dicts."""
    if _is_list_of_dicts(node, dict_vars):
        return True
    return isinstance(node, ast.Name) and node.id in list_dict_vars


def _scope_nodes(func: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    """Yield nodes in the function's own scope, not descending into nested defs/lambdas."""
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                stack.append(child)


def _constructs_new_dicts(func: Callable[..., Any]) -> bool:
    """True if the UDF returns freshly-built dicts (merge/expand), not the items it received.

    Mirrors the runtime discriminator: returning a list of plain dicts crashes,
    while returning input items or a FileUDFResult is safe. A dict literal used
    only as a local lookup table (never returned or appended to a returned list)
    is not construction. A UDF whose source cannot be read is left unflagged.
    """
    try:
        source = inspect.getsource(func)
    except (OSError, TypeError):
        return False
    return _source_constructs_new_dicts(textwrap.dedent(source))


def _source_constructs_new_dicts(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    fn = next(
        (n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None
    )
    if fn is None:
        return False
    nodes = list(_scope_nodes(fn))

    # Names bound to a freshly-built dict, to a fixpoint (covers d2 = d1 chains).
    dict_vars: set[str] = set()
    while True:
        before = len(dict_vars)
        for node in nodes:
            if isinstance(node, ast.Assign) and _is_dict_construct(node.value, dict_vars):
                dict_vars |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            elif (
                isinstance(node, (ast.AnnAssign, ast.NamedExpr))
                and node.value is not None
                and isinstance(node.target, ast.Name)
                and _is_dict_construct(node.value, dict_vars)
            ):
                dict_vars.add(node.target.id)
        if len(dict_vars) == before:
            break

    # List accumulators that receive freshly-built dicts, to a fixpoint so an
    # accumulator aliased to another name (out = results) is tracked too.
    list_dict_vars: set[str] = set()
    while True:
        before = len(list_dict_vars)
        for node in nodes:
            if isinstance(node, ast.Assign) and _feeds_dicts(node.value, dict_vars, list_dict_vars):
                list_dict_vars |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            elif (
                isinstance(node, ast.AnnAssign)
                and node.value is not None
                and isinstance(node.target, ast.Name)
                and _feeds_dicts(node.value, dict_vars, list_dict_vars)
            ):
                list_dict_vars.add(node.target.id)
            elif (
                isinstance(node, ast.AugAssign)
                and isinstance(node.target, ast.Name)
                and _is_list_of_dicts(node.value, dict_vars)
            ):
                list_dict_vars.add(node.target.id)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.args
            ):
                if node.func.attr == "append" and _is_dict_construct(node.args[0], dict_vars):
                    list_dict_vars.add(node.func.value.id)
                elif node.func.attr == "extend" and _is_list_of_dicts(node.args[0], dict_vars):
                    list_dict_vars.add(node.func.value.id)
        if len(list_dict_vars) == before:
            break

    # Construction is only a problem when the freshly-built dicts are returned —
    # a list wrapped in FileUDFResult(...) is a call, not a bare dict/list, so it
    # is safe and correctly not matched here.
    for node in nodes:
        if isinstance(node, ast.Return) and node.value is not None:
            value = node.value
            if _is_dict_construct(value, dict_vars) or _feeds_dicts(
                value, dict_vars, list_dict_vars
            ):
                return True
    return False


def find_file_udf_contract_warnings(
    registry: dict[str, dict], referenced: set[str] | None = None
) -> list[str]:
    """Return one warning per FILE-mode UDF that returns freshly-built dicts, not FileUDFResult.

    When *referenced* is given, only UDFs named in it are checked — the warning
    predicts a runtime crash, which can only happen for UDFs the workflow calls.
    """
    refs_lower = {r.lower() for r in referenced} if referenced is not None else None
    warnings: list[str] = []
    for meta in registry.values():
        if meta.get("granularity") is not Granularity.FILE:
            continue
        if refs_lower is not None and meta["name"].lower() not in refs_lower:
            continue
        annotation = meta["signature"].return_annotation
        if _returns_fileudfresult(annotation):
            continue
        if not _constructs_new_dicts(meta["function"]):
            continue
        warnings.append(
            f"FILE-mode UDF '{meta['name']}' returns {annotation!r}, not FileUDFResult. "
            f"If it constructs new dicts, wrap them in FileUDFResult(outputs=[{{source_index, data}}]); "
            f"if it round-trips input items unchanged (filter mode), this is safe to ignore."
        )
    return warnings
