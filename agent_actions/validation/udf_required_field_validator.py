"""Static-AST check: a kind:tool UDF must unconditionally emit every required
output-schema field, or `_validate_udf_output` crashes mid-run whenever a
guard misses. Errs toward silence — unrecognised construction shapes yield
no warning, so unconditionally-emitting tools stay clean."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path


def _has_spread(dict_node: ast.Dict) -> bool:
    """True if the dict literal has ``**x`` unpacking — content unknowable."""
    return any(k is None for k in dict_node.keys)


def _const_str_keys(dict_node: ast.Dict) -> set[str]:
    """Constant string keys from a dict literal — spreads and dynamic keys skipped."""
    keys: set[str] = set()
    for k in dict_node.keys:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.add(k.value)
    return keys


def _iter_own_returns(func: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.Return]:
    """Yield every ``Return`` belonging to ``func`` — never one from a nested function.

    A plain ``ast.walk`` descends into inner ``FunctionDef``/``AsyncFunctionDef``
    / ``Lambda`` nodes and would pick their returns as candidates for the outer
    tail return, silently misclassifying the outer's output shape.
    """
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _last_return(func: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Return | None:
    """The tail return, chosen by source order — early guard returns must not shadow it."""
    returns = list(_iter_own_returns(func))
    if not returns:
        return None
    return max(returns, key=lambda r: r.lineno)


def _file_udf_result_data(node: ast.expr) -> set[str] | None:
    """Constant keys of the `data` mappings in an inline ``FileUDFResult`` return.

    ``None`` when the node is not a FileUDFResult call, or its ``outputs`` are
    built dynamically — the caller then falls through to its own handling.
    """
    if not (isinstance(node, ast.Call) and _callee_name(node.func) == "FileUDFResult"):
        return None
    outputs = next(
        (kw.value for kw in node.keywords if kw.arg == "outputs"),
        node.args[0] if node.args else None,
    )
    if not isinstance(outputs, ast.List) or not outputs.elts:
        return None
    # Each output row is validated on its own, so a key is guaranteed only when
    # every row carries it — intersect across rows rather than union.
    per_row: list[set[str]] = []
    for element in outputs.elts:
        if not isinstance(element, ast.Dict) or _has_spread(element):
            return None
        data = next(
            (
                value
                for key, value in zip(element.keys, element.values, strict=True)
                if isinstance(key, ast.Constant) and key.value == "data"
            ),
            None,
        )
        if not isinstance(data, ast.Dict) or _has_spread(data):
            return None
        per_row.append(_const_str_keys(data))
    return set.intersection(*per_row)


def _callee_name(func: ast.expr) -> str | None:
    """Bare name of a call target, whether called directly or via a module."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_mapping_literal(node: ast.expr | None) -> bool:
    """A dict display, or a ``dict(k=v, ...)`` call whose keys are all spelled out."""
    if isinstance(node, ast.Dict):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "dict"
        and not node.args
    )


def _mapping_literal_keys(node: ast.expr) -> set[str] | None:
    """Constant keys of a mapping literal; ``None`` when a ``**spread`` hides some."""
    if isinstance(node, ast.Dict):
        return None if _has_spread(node) else _const_str_keys(node)
    assert isinstance(node, ast.Call)
    if any(kw.arg is None for kw in node.keywords):
        return None
    return {kw.arg for kw in node.keywords if kw.arg is not None}


def _is_name(node: ast.expr, target: str) -> bool:
    return isinstance(node, ast.Name) and node.id == target


def _initial_mapping(stmt: ast.stmt, target: str) -> ast.expr | None:
    """The mapping literal ``stmt`` binds to ``target`` (``target = ...`` or ``target: T = ...``)."""
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        bound, value = stmt.targets[0], stmt.value
    elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
        bound, value = stmt.target, stmt.value
    else:
        return None
    if _is_name(bound, target) and _is_mapping_literal(value):
        return value
    return None


def _keys_added(stmt: ast.stmt, target: str) -> set[str] | None:
    """Keys ``stmt`` puts on ``target`` by name; empty when it adds none, ``None`` when unknowable.

    Reads ``target["k"] = v``, ``target |= {...}``, ``target.update({...}, k=v)``
    and ``target.setdefault("k", v)``.
    """
    if isinstance(stmt, ast.AnnAssign) and stmt.value is None:
        return set()
    if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        return {
            t.slice.value
            for t in targets
            if isinstance(t, ast.Subscript)
            and _is_name(t.value, target)
            and isinstance(t.slice, ast.Constant)
            and isinstance(t.slice.value, str)
        }
    if (
        isinstance(stmt, ast.AugAssign)
        and isinstance(stmt.op, ast.BitOr)
        and _is_name(stmt.target, target)
        and _is_mapping_literal(stmt.value)
    ):
        return _mapping_literal_keys(stmt.value)
    if not (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Attribute)
        and _is_name(stmt.value.func.value, target)
    ):
        return set()
    call = stmt.value
    method = stmt.value.func.attr
    if method == "setdefault":
        first = call.args[0] if call.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return {first.value}
        return set()
    if method != "update":
        return set()
    if any(kw.arg is None for kw in call.keywords):
        return None
    keys = {kw.arg for kw in call.keywords if kw.arg is not None}
    if call.args:
        if not isinstance(call.args[0], ast.Dict):
            return set()
        if _has_spread(call.args[0]):
            return None
        keys |= _const_str_keys(call.args[0])
    return keys


def _top_level_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Statements that run on every path; a ``with`` block's body runs whenever it is entered."""
    for stmt in body:
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            yield from _top_level_statements(stmt.body)
        else:
            yield stmt


def _returned_name(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    ret = _last_return(func)
    if ret is not None and isinstance(ret.value, ast.Name):
        return ret.value.id
    return None


def _unconditional_output_keys(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str] | None:
    """The constant string keys the UDF puts on its returned mapping without any guard.

    Returns None when the returned shape is unrecognisable (list/scalar return,
    a helper-call initialiser, a ``**spread`` in the returned literal, etc.).
    None means "decline to decide" — the caller emits no warning.
    """
    ret = _last_return(func)
    if ret is None or ret.value is None:
        return None
    # `return {...}` — the literal's constant keys are the unconditional set.
    if _is_mapping_literal(ret.value):
        return _mapping_literal_keys(ret.value)
    # `return name` — walk the function's TOP-LEVEL body only. Anything nested
    # in if/for/while/try is by definition conditional.
    if not isinstance(ret.value, ast.Name):
        return None
    target = ret.value.id
    keys: set[str] = set()
    initial_found = False
    for stmt in _top_level_statements(func.body):
        initial = _initial_mapping(stmt, target)
        if initial is not None:
            initial_keys = _mapping_literal_keys(initial)
            if initial_keys is None:
                return None
            keys |= initial_keys
            initial_found = True
            continue
        added = _keys_added(stmt, target)
        if added is None:
            return None
        keys |= added
    if not initial_found:
        # No dict-literal initial assignment (e.g. `result = build(data)` or
        # `result = data.copy()`): we cannot enumerate what the helper puts
        # in, so declining is safer than flagging every required field.
        return None
    return keys


_BLOCK_NAMES: dict[type, str] = {
    ast.If: "an `if`",
    ast.For: "a `for` loop",
    ast.AsyncFor: "an `async for` loop",
    ast.While: "a `while` loop",
    ast.Try: "a `try`",
    ast.Match: "a `match`",
}


def _where_set(func: ast.FunctionDef | ast.AsyncFunctionDef, field: str) -> tuple[int, str] | None:
    """The first line that sets ``field`` on the returned name by name, and the block it sits in."""
    target = _returned_name(func)
    if target is None:
        return None
    found: list[tuple[int, str]] = []

    def visit(body: list[ast.stmt], block: str | None) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            added = _keys_added(stmt, target)
            if block is not None and added and field in added:
                found.append((stmt.lineno, block))
            inner = _BLOCK_NAMES.get(type(stmt), block)
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, ast.match_case):
                    visit(child.body, inner)
                elif isinstance(child, ast.ExceptHandler):
                    visit(child.body, "an `except`")
            for name in ("body", "orelse", "finalbody"):
                nested = getattr(stmt, name, None)
                if isinstance(nested, list) and nested and isinstance(nested[0], ast.stmt):
                    visit(nested, inner)

    visit(func.body, None)
    return min(found) if found else None


def unconditional_output_keys(source: str) -> set[str] | None:
    """The output keys a UDF's source provably emits on every path.

    ``None`` means the returned shape could not be read — callers must treat
    that as "unknown", never as "emits nothing". Reads the FileUDFResult
    envelope that `find_conditional_required_field_risks` declines on, so it
    must stay out of that check: seeing FILE tools for the first time there
    would turn a warning-free project into a refused one.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ret = _last_return(node)
            if ret is not None and ret.value is not None:
                envelope = _file_udf_result_data(ret.value)
                if envelope is not None:
                    return envelope
            return _unconditional_output_keys(node)
    return None


def find_conditional_required_field_risks(actions: dict[str, dict]) -> list[str]:
    """One finding per required schema field a kind:tool UDF cannot statically
    be shown to emit unconditionally.

    Each action's info carries ``source`` and ``required``; ``file`` and
    ``first_line`` (the source's first line in that file), when given, let a
    finding cite the file line that sets the field.
    ``additional_properties`` does not weaken the check — extra keys allowed
    does not make a missing required key permissible.
    """
    findings: list[str] = []
    for name, info in actions.items():
        required = info.get("required") or []
        source = info.get("source", "")
        if not required or not source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        func = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            None,
        )
        if func is None:
            continue
        emitted = _unconditional_output_keys(func)
        if emitted is None:
            continue
        for field in required:
            if field not in emitted:
                findings.append(_finding(name, func, field, info))
    return findings


def _finding(
    action: str, func: ast.FunctionDef | ast.AsyncFunctionDef, field: str, info: dict
) -> str:
    where = _where_set(func, field)
    if where is None:
        how = "sets it only through a computed key, or not at all"
        consequence = "a record without it"
    else:
        line, block = where
        first_line = info.get("first_line")
        file = info.get("file")
        if isinstance(first_line, int):
            line += first_line - 1
        located = f"line {line} of {Path(file).name}" if file else f"line {line}"
        how = f"sets it only at {located}, inside {block}"
        consequence = "a record that does not take that path"
    return (
        f"{action}: output schema requires '{field}' but the tool '{func.name}' {how}, "
        f"so {consequence} fails output validation at run time. Make '{field}' "
        f"optional in the schema, or set it on every path in the tool."
    )
