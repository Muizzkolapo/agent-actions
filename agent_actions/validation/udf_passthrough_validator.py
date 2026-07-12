"""Flag kind:tool UDFs that return bus-derived pass-through dicts under a strict schema."""

from __future__ import annotations

import ast


def _target_names(target: ast.AST) -> set[str]:
    """Names bound by an assignment or ``for`` target."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for elt in target.elts:
            names |= _target_names(elt)
        return names
    return set()


def _root_is_data(node: ast.AST) -> bool:
    """True if an attribute/subscript/call chain is ultimately rooted at name ``data``."""
    current = node
    while True:
        if isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Attribute):
            current = current.value
        elif isinstance(current, ast.Subscript):
            current = current.value
        else:
            break
    return isinstance(current, ast.Name) and current.id == "data"


def _is_bus_read(node: ast.AST) -> bool:
    """True for ``data[...]`` or a ``data.get(...)`` chain — a read straight off the bus."""
    if isinstance(node, ast.Subscript) and _root_is_data(node):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and _root_is_data(node.func.value)
    )


def _is_derived(node: ast.AST, tainted: set[str]) -> bool:
    """True if *node* carries bus data through unchanged (opaque keys), not a fresh literal.

    A dict/list literal and a call to any other function are construction
    boundaries — their key set is bounded by the code, so they are not derived.
    """
    if _is_bus_read(node):
        return True
    if isinstance(node, ast.Name):
        return node.id in tainted
    if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
        local = set(tainted)
        for gen in node.generators:
            if _is_derived(gen.iter, local):
                local |= _target_names(gen.target)
        return _is_derived(node.elt, local)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_is_derived(elt, tainted) for elt in node.elts)
    return False


def _bus_tainted_names(func: ast.AST) -> set[str]:
    """Local names holding bus-derived values, to a fixpoint over the function body."""
    tainted: set[str] = set()
    while True:
        before = len(tainted)
        for node in ast.walk(func):
            if isinstance(node, ast.For) and _is_derived(node.iter, tainted):
                tainted |= _target_names(node.target)
            elif isinstance(node, ast.comprehension) and _is_derived(node.iter, tainted):
                tainted |= _target_names(node.target)
            elif isinstance(node, ast.Assign) and _is_derived(node.value, tainted):
                for tgt in node.targets:
                    tainted |= _target_names(tgt)
            elif (
                isinstance(node, (ast.AnnAssign, ast.NamedExpr))
                and node.value is not None
                and _is_derived(node.value, tainted)
            ):
                tainted |= _target_names(node.target)
        if len(tainted) == before:
            return tainted


def _returns_passthrough(func: ast.AST, tainted: set[str]) -> bool:
    """True if a bus-derived value reaches the function's output (return/append/extend/+=)."""
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None:
            if _is_derived(node.value, tainted):
                return True
        elif isinstance(node, ast.AugAssign) and _is_derived(node.value, tainted):
            return True
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("append", "extend")
            and isinstance(node.func.value, ast.Name)
            and node.args
            and _is_derived(node.args[0], tainted)
        ):
            return True
    return False


def _source_is_passthrough(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for func in ast.walk(tree):
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _returns_passthrough(func, _bus_tainted_names(func)):
                return True
    return False


def find_passthrough_schema_risks(actions: dict[str, dict]) -> list[str]:
    """Return one warning per kind:tool action whose UDF passes bus dicts through a strict schema.

    Each action entry provides ``source`` (UDF text) and ``additional_properties`` (bool);
    actions that opt out with ``additional_properties: True`` are never flagged.
    """
    findings: list[str] = []
    for name, info in actions.items():
        if info.get("additional_properties"):
            continue
        if _source_is_passthrough(info.get("source", "")):
            findings.append(
                f"{name}: UDF passes upstream dicts through unchanged, but its schema is strict "
                f"(additionalProperties not true). Extra upstream keys will be rejected at runtime "
                f"— add them to the schema fields or set additionalProperties: true."
            )
    return findings
