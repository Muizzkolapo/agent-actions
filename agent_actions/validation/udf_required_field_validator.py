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


class _Decline(Exception):
    """The returned mapping's keys cannot be read; the caller makes no claim."""


class _Unreached:
    """No path gets here: every one raised or returned before."""


_UNREACHED = _Unreached()

# The keys a path's mapping is known to hold. None when its contents are unknown (a
# parameter, a helper's result), which bounds nothing: such a path neither adds a key
# nor takes one away when paths are joined.
_State = frozenset[str] | None | _Unreached


def _merge(states: list[_State]) -> _State:
    """The keys every path holds, over the paths that reach this point."""
    live = [s for s in states if not isinstance(s, _Unreached)]
    if not live:
        return _UNREACHED
    known = [s for s in live if s is not None]
    if not known:
        return None
    return frozenset.intersection(*known)


def _walk_own(nodes: list[ast.AST]) -> Iterator[ast.AST]:
    """Every node under ``nodes`` that runs in this scope — not a nested def, lambda or class body."""
    stack = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _const_key(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _removals(nodes: list[ast.AST], target: str) -> tuple[set[str], bool]:
    """Keys ``nodes`` remove from ``target`` by name, and whether they may empty it.

    Reads ``del target["k"]``, ``target.pop("k", ...)`` and ``target.clear()``; a key
    removed by a computed name, or ``popitem()``, is unknowable and declines.
    """
    removed: set[str] = set()
    cleared = False
    for node in _walk_own(nodes):
        if isinstance(node, ast.Delete):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and _is_name(t.value, target):
                    key = _const_key(t.slice)
                    if key is None:
                        raise _Decline
                    removed.add(key)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and _is_name(node.func.value, target)
        ):
            method = node.func.attr
            if method == "pop":
                key = _const_key(node.args[0]) if node.args else None
                if key is None:
                    raise _Decline
                removed.add(key)
            elif method == "popitem":
                raise _Decline
            elif method == "clear":
                cleared = True
    return removed, cleared


def _binds_name(node: ast.AST | None, target: str) -> bool:
    """True if ``node``, an assignment target, binds ``target`` (directly or by unpacking)."""
    if isinstance(node, ast.Name):
        return node.id == target
    if isinstance(node, (ast.Tuple, ast.List)):
        return any(_binds_name(e, target) for e in node.elts)
    if isinstance(node, ast.Starred):
        return _binds_name(node.value, target)
    return False


def _rebinds(nodes: list[ast.AST], target: str) -> bool:
    """True if ``nodes`` may bind ``target`` to something new, in any spelling."""
    for node in _walk_own(nodes):
        if isinstance(node, ast.Assign) and any(_binds_name(t, target) for t in node.targets):
            return True
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            if _binds_name(node.target, target):
                return True
        if isinstance(node, ast.AugAssign) and _binds_name(node.target, target):
            # `target |= {...}` only adds keys to the mapping it already holds.
            if not isinstance(node.op, ast.BitOr):
                return True
        if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            if _binds_name(node.target, target):
                return True
        if isinstance(node, ast.withitem) and _binds_name(node.optional_vars, target):
            return True
        if isinstance(node, ast.NamedExpr) and _binds_name(node.target, target):
            return True
        if isinstance(node, ast.Delete) and any(_binds_name(t, target) for t in node.targets):
            return True
        if isinstance(node, ast.ExceptHandler) and node.name == target:
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == target:
                return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if any((alias.asname or alias.name.split(".")[0]) == target for alias in node.names):
                return True
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == target:
            return True
        if isinstance(node, ast.MatchMapping) and node.rest == target:
            return True
    return False


def _header(stmt: ast.stmt) -> list[ast.AST]:
    """The parts of ``stmt`` that run before any block it holds — all of it for a simple one."""
    if isinstance(stmt, (ast.If, ast.While)):
        return [stmt.test]
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        return [stmt.iter, stmt.target]
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return list(stmt.items)
    if isinstance(stmt, ast.Match):
        return [stmt.subject]
    if isinstance(stmt, (ast.Try, ast.TryStar, ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    if isinstance(stmt, ast.ClassDef):
        return []
    return [stmt]


def _without(keys: _State, nodes: list[ast.AST], target: str) -> _State:
    """``keys`` less what ``nodes`` remove from ``target``."""
    if not isinstance(keys, frozenset):
        return keys
    removed, cleared = _removals(nodes, target)
    return frozenset() if cleared else keys - removed


_COMPOUND = (ast.If, ast.While, ast.For, ast.AsyncFor, ast.With, ast.AsyncWith, ast.Match)


def _is_irrefutable(case: ast.match_case) -> bool:
    pattern = case.pattern
    while isinstance(pattern, ast.MatchAs) and pattern.pattern is not None:
        pattern = pattern.pattern
    return case.guard is None and isinstance(pattern, ast.MatchAs) and pattern.pattern is None


class _OutputFlow:
    """Walks a UDF's body path by path, tracking the keys its returned name holds.

    A key counts only when every path that reaches the tail return holds it: an ``if``
    keeps what both branches hold, a loop body may run no times so it only removes, and
    a ``try`` joins its body's end with each ``except`` that falls through. A path that
    raises or returns elsewhere never reaches the tail and adds nothing.
    """

    def __init__(self, target: str, tail: ast.Return) -> None:
        self.target = target
        self.tail = tail
        self.at_tail: list[_State] = []

    def block(self, body: list[ast.stmt], state: _State) -> _State:
        for stmt in body:
            if isinstance(state, _Unreached):
                break
            state = self.stmt(stmt, state)
        return state

    def may(self, nodes: list[ast.AST], state: _State) -> _State:
        """``state`` after code that may run any number of times, or not at all: only its removals hold.

        A path on which that code re-binds the name holds unknown contents, which bound nothing.
        """
        return _without(state, nodes, self.target)

    def stmt(self, stmt: ast.stmt, state: _State) -> _State:
        target = self.target
        state = _without(state, _header(stmt), target)
        if isinstance(stmt, ast.Return):
            if stmt is self.tail:
                self.at_tail.append(state)
            return _UNREACHED
        if isinstance(stmt, ast.Raise):
            return _UNREACHED
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return None if stmt.name == target else state
        if isinstance(stmt, _COMPOUND) and _rebinds(_header(stmt), target):
            state = None
        if isinstance(stmt, ast.If):
            return _merge([self.block(stmt.body, state), self.block(stmt.orelse, state)])
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            return self.block(stmt.body, state)
        if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            return self.may([stmt], state)
        if isinstance(stmt, (ast.Try, ast.TryStar)):
            finished = self.block(stmt.orelse, self.block(stmt.body, state))
            # A handler starts wherever the body raised, so it holds only what the body cannot remove.
            entry = self.may(list(stmt.body), state)
            handled = [
                self.block(handler.body, None if handler.name == target else entry)
                for handler in stmt.handlers
            ]
            return self.block(stmt.finalbody, _merge([finished, *handled]))
        if isinstance(stmt, ast.Match):
            outcomes = [
                self.block(case.body, None if _rebinds([case.pattern], target) else state)
                for case in stmt.cases
            ]
            if not any(_is_irrefutable(case) for case in stmt.cases):
                outcomes.append(state)
            return _merge(outcomes)
        return self.simple(stmt, state)

    def simple(self, stmt: ast.stmt, state: _State) -> _State:
        target = self.target
        literal = _initial_mapping(stmt, target)
        if literal is not None:
            keys = _mapping_literal_keys(literal)
            return None if keys is None else frozenset(keys)
        if _rebinds([stmt], target):
            return None
        added = _keys_added(stmt, target)
        if added is None:
            raise _Decline
        return state | added if isinstance(state, frozenset) else state


def _returned_value(func: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    """What the tail return hands back; a one-element list stands for its element.

    Each item of a returned list is validated on its own, so ``return [out]`` is
    checked exactly as ``return out``.
    """
    ret = _last_return(func)
    if ret is None or ret.value is None:
        return None
    value = ret.value
    if isinstance(value, ast.List) and len(value.elts) == 1:
        element = value.elts[0]
        if not isinstance(element, ast.Starred):
            return element
    return value


def _returned_name(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    value = _returned_value(func)
    if isinstance(value, ast.Name):
        return value.id
    return None


def _unconditional_output_keys(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str] | None:
    """The constant string keys the UDF's returned mapping holds on every path to its tail return.

    Returns None when the returned shape is unrecognisable (a scalar or longer list
    return, a helper-call initialiser, a ``**spread``, a key removed by a computed
    name, a tail return inside a loop, etc.). None means "decline to decide" — the
    caller emits no warning.
    """
    value = _returned_value(func)
    if value is None:
        return None
    if _is_mapping_literal(value):
        return _mapping_literal_keys(value)
    if not isinstance(value, ast.Name):
        return None
    tail = _last_return(func)
    assert tail is not None
    flow = _OutputFlow(value.id, tail)
    try:
        flow.block(func.body, None)
    except _Decline:
        return None
    reached = _merge(flow.at_tail)
    if not isinstance(reached, frozenset):
        # Never bound to a literal on the way (e.g. `result = build(data)`), or the tail
        # return sits in a loop: what it holds cannot be enumerated, so decline.
        return None
    return set(reached)


_BLOCK_NAMES: dict[type, str] = {
    ast.If: "an `if`",
    ast.For: "a `for` loop",
    ast.AsyncFor: "an `async for` loop",
    ast.While: "a `while` loop",
    ast.Try: "a `try`",
    ast.TryStar: "a `try`",
    ast.Match: "a `match`",
}


def _statements(body: list[ast.stmt], block: str | None) -> Iterator[tuple[ast.stmt, str | None]]:
    """Every statement in this scope, in source order, with the block it sits in (None at top)."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield stmt, block
        inner = _BLOCK_NAMES.get(type(stmt), block)
        if isinstance(stmt, (ast.Try, ast.TryStar)):
            yield from _statements(stmt.body, inner)
            for handler in stmt.handlers:
                yield from _statements(handler.body, "an `except`")
            yield from _statements(stmt.orelse, inner)
            yield from _statements(stmt.finalbody, inner)
        elif isinstance(stmt, ast.Match):
            for case in stmt.cases:
                yield from _statements(case.body, inner)
        else:
            for name in ("body", "orelse"):
                nested = getattr(stmt, name, None)
                if isinstance(nested, list):
                    yield from _statements(nested, inner)


def _where_set(func: ast.FunctionDef | ast.AsyncFunctionDef, field: str) -> tuple[int, str] | None:
    """The first line that sets ``field`` on the returned name by name, and the block it sits in."""
    target = _returned_name(func)
    if target is None:
        return None
    found = [
        (stmt.lineno, block)
        for stmt, block in _statements(func.body, None)
        if block is not None and field in (_keys_added(stmt, target) or ())
    ]
    return min(found) if found else None


def _where_dropped(
    func: ast.FunctionDef | ast.AsyncFunctionDef, field: str
) -> tuple[int, str, str | None] | None:
    """The first line that removes ``field`` from the returned name, or re-binds it without it."""
    target = _returned_name(func)
    if target is None:
        return None
    put = False
    for stmt, block in _statements(func.body, None):
        try:
            removed, cleared = _removals(_header(stmt), target)
        except _Decline:
            removed, cleared = set(), False
        if put and (field in removed or cleared):
            return stmt.lineno, "removes it", block
        literal = _initial_mapping(stmt, target)
        keys = _mapping_literal_keys(literal) if literal is not None else _keys_added(stmt, target)
        if literal is not None and put and keys is not None and field not in keys:
            return stmt.lineno, f"re-binds '{target}' without it", block
        put = put or field in (keys or ())
    return None


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
    dropped = _where_dropped(func, field)
    where = _where_set(func, field)
    if dropped is not None:
        line, verb, block = dropped
        how = f"{verb} at {_located(line, info)}" + (f", inside {block}" if block else "")
        consequence = "a record returned without it"
    elif where is None:
        how = "sets it only through a computed key, or not at all"
        consequence = "a record without it"
    else:
        line, block = where
        how = f"sets it only at {_located(line, info)}, inside {block}"
        consequence = "a record that does not take that path"
    return (
        f"{action}: output schema requires '{field}' but the tool '{func.name}' {how}, "
        f"so {consequence} fails output validation at run time. Make '{field}' "
        f"optional in the schema, or set it on every path in the tool."
    )


def _located(line: int, info: dict) -> str:
    """``line`` of the UDF's source as a line of its file, when the file is known."""
    first_line = info.get("first_line")
    file = info.get("file")
    if isinstance(first_line, int):
        line += first_line - 1
    return f"line {line} of {Path(file).name}" if file else f"line {line}"
