"""Static-AST check: every return of a kind:tool UDF must emit every required
output-schema field, or `_validate_udf_output` crashes mid-run whenever a
guard misses. Errs toward silence — unrecognised construction shapes yield
no warning, so unconditionally-emitting tools stay clean."""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
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
    / ``Lambda`` nodes and would pick their returns as the outer's, silently
    misclassifying the outer's output shape.
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
    """The tail return, chosen by source order."""
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
        # A `**spread` or a computed key could put any key in it.
        if any(k is None or not isinstance(k, ast.Constant) for k in node.keys):
            return None
        return _const_str_keys(node)
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


def _key_name(node: ast.expr | None, names: Mapping[str, str] | None) -> str | None:
    """The key ``node`` names: a string constant, or a loop variable bound to one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if names and isinstance(node, ast.Name):
        return names.get(node.id)
    return None


def _flat_targets(targets: list[ast.expr]) -> Iterator[ast.expr]:
    for t in targets:
        if isinstance(t, (ast.Tuple, ast.List)):
            yield from _flat_targets(t.elts)
        elif isinstance(t, ast.Starred):
            yield from _flat_targets([t.value])
        else:
            yield t


def _keys_added(
    stmt: ast.stmt, target: str, names: Mapping[str, str] | None = None
) -> set[str] | None:
    """Keys ``stmt`` puts on ``target`` by name; empty when it adds none, ``None`` when unknowable.

    Reads ``target["k"] = v``, ``target |= {...}``, ``target.update({...}, k=v)``
    and ``target.setdefault("k", v)``. A key named by anything but a constant (or a
    loop variable over constants, in ``names``), or merged in from something other
    than a literal, could be any key, so the statement is unknowable.
    """
    if isinstance(stmt, ast.AnnAssign) and stmt.value is None:
        return set()
    if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        keys: set[str] = set()
        for t in _flat_targets(targets):
            if isinstance(t, ast.Subscript) and _is_name(t.value, target):
                key = _key_name(t.slice, names)
                if key is None:
                    return None
                keys.add(key)
        return keys
    if (
        isinstance(stmt, ast.AugAssign)
        and isinstance(stmt.op, ast.BitOr)
        and _is_name(stmt.target, target)
    ):
        return _mapping_literal_keys(stmt.value) if _is_mapping_literal(stmt.value) else None
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
        key = _key_name(call.args[0] if call.args else None, names)
        return None if key is None else {key}
    if method != "update":
        return set()
    if any(kw.arg is None for kw in call.keywords) or len(call.args) > 1:
        return None
    keys = {kw.arg for kw in call.keywords if kw.arg is not None}
    if call.args:
        literal = _mapping_literal_keys(call.args[0]) if _is_mapping_literal(call.args[0]) else None
        if literal is None:
            return None
        keys |= literal
    return keys


class _Decline(Exception):
    """The returned mapping's keys cannot be read; the caller makes no claim."""


class _Unreached:
    """No path gets here: every one raised or returned before."""


_UNREACHED = _Unreached()

# The keys a path's mapping is known to hold. None when its contents are unknown (a
# parameter, a helper's result); joined with any other path, that stays unknown.
_State = frozenset[str] | None | _Unreached


def _merge(states: list[_State]) -> _State:
    """The keys every path holds, over the paths that reach this point.

    One path holding unknown contents makes the join unknown: it may lack any key.
    """
    live = [s for s in states if not isinstance(s, _Unreached)]
    if not live:
        return _UNREACHED
    known = [s for s in live if s is not None]
    if len(known) < len(live):
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


def _removals(
    nodes: list[ast.AST], target: str, names: Mapping[str, str] | None = None
) -> tuple[set[str], bool]:
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
                    key = _key_name(t.slice, names)
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
                key = _key_name(node.args[0] if node.args else None, names)
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


def _without(
    keys: _State, nodes: list[ast.AST], target: str, names: Mapping[str, str] | None = None
) -> _State:
    """``keys`` less what ``nodes`` remove from ``target``."""
    if not isinstance(keys, frozenset):
        return keys
    removed, cleared = _removals(nodes, target, names)
    return frozenset() if cleared else keys - removed


_COMPOUND = (ast.If, ast.While, ast.For, ast.AsyncFor, ast.With, ast.AsyncWith, ast.Match)


def _is_irrefutable(case: ast.match_case) -> bool:
    pattern = case.pattern
    while isinstance(pattern, ast.MatchAs) and pattern.pattern is not None:
        pattern = pattern.pattern
    return case.guard is None and isinstance(pattern, ast.MatchAs) and pattern.pattern is None


def _constant_loop(stmt: ast.stmt) -> tuple[str, list[str]] | None:
    """``for name in ("a", "b"):`` — the loop variable and the constants it takes, in order."""
    if not (
        isinstance(stmt, ast.For)
        and isinstance(stmt.target, ast.Name)
        and isinstance(stmt.iter, (ast.Tuple, ast.List))
    ):
        return None
    values = [_key_name(e, None) for e in stmt.iter.elts]
    if any(v is None for v in values):
        return None
    return stmt.target.id, [v for v in values if v is not None]


def _always_true(test: ast.expr) -> bool:
    return isinstance(test, ast.Constant) and bool(test.value)


# A loop's state only shrinks pass by pass, so a real body never reaches this.
_MAX_LOOP_PASSES = 64


class _Loop:
    """The states that leave a loop body early, by ``break`` and by ``continue``."""

    def __init__(self) -> None:
        self.breaks: list[_State] = []
        self.continues: list[_State] = []


class _OutputFlow:
    """Walks a UDF's body path by path, tracking the keys the name ``target`` holds.

    A key counts at a ``return target`` only when every path that reaches it holds it:
    an ``if`` keeps what both branches hold, a loop keeps what holds after any number
    of passes (none included), and a ``try`` joins its body's end with each ``except``
    that falls through. A path that raises or returns ends there. Every return a path
    reaches is noted in ``reached``; with no ``target`` the walk notes only that.
    """

    def __init__(self, target: str = "") -> None:
        self.target = target
        self.at_return: dict[ast.Return, list[_State]] = {}
        self.reached: set[ast.Return] = set()
        self.loops: list[_Loop] = []
        self.names: dict[str, str] = {}

    def block(self, body: list[ast.stmt], state: _State) -> _State:
        for stmt in body:
            if isinstance(state, _Unreached):
                break
            state = self.stmt(stmt, state)
        return state

    def anywhere_in(self, body: list[ast.stmt], state: _State) -> _State:
        """What holds at every point of ``body``, where an ``except`` may start.

        A re-binding anywhere in it leaves the contents unknown there.
        """
        if _rebinds(list(body), self.target):
            return None
        return _without(state, list(body), self.target, self.names)

    def stmt(self, stmt: ast.stmt, state: _State) -> _State:
        target = self.target
        state = _without(state, _header(stmt), target, self.names)
        if isinstance(stmt, ast.Return):
            self.reached.add(stmt)
            if target and _returned_name_of(stmt) == target:
                # A return inside a loop is left unread: no claim is made about it.
                self.at_return.setdefault(stmt, []).append(None if self.loops else state)
            return _UNREACHED
        if isinstance(stmt, ast.Raise):
            return _UNREACHED
        if isinstance(stmt, ast.Break):
            self.loops[-1].breaks.append(state)
            return _UNREACHED
        if isinstance(stmt, ast.Continue):
            self.loops[-1].continues.append(state)
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
            return self.loop(stmt, state)
        if isinstance(stmt, (ast.Try, ast.TryStar)):
            finished = self.block(stmt.orelse, self.block(stmt.body, state))
            entry = self.anywhere_in(stmt.body, state)
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

    def loop(self, stmt: ast.For | ast.AsyncFor | ast.While, state: _State) -> _State:
        frame = _Loop()
        self.loops.append(frame)
        try:
            constant = _constant_loop(stmt)
            if constant is not None:
                state = self._unrolled(stmt, frame, state, *constant)
            else:
                state = self._to_fixpoint(stmt, frame, state)
        finally:
            self.loops.pop()
        if isinstance(stmt, ast.While) and _always_true(stmt.test):
            # `while True:` runs its body at least once and leaves only by `break`.
            return _merge(frame.breaks)
        return _merge([self.block(stmt.orelse, state), *frame.breaks])

    def _unrolled(
        self, stmt: ast.stmt, frame: _Loop, state: _State, variable: str, values: list[str]
    ) -> _State:
        """A loop over constant names runs its body once per name, in order."""
        assert isinstance(stmt, ast.For)
        outer = self.names.get(variable)
        try:
            for value in values:
                self.names[variable] = value
                frame.continues = []
                state = _merge([self.block(stmt.body, state), *frame.continues])
        finally:
            if outer is None:
                self.names.pop(variable, None)
            else:
                self.names[variable] = outer
        return state

    def _to_fixpoint(
        self, stmt: ast.For | ast.AsyncFor | ast.While, frame: _Loop, state: _State
    ) -> _State:
        """What holds after any number of passes, joined until another pass changes nothing."""
        current = state
        for _ in range(_MAX_LOOP_PASSES):
            frame.breaks, frame.continues = [], []
            head = current
            if isinstance(stmt, ast.While):
                head = _without(current, [stmt.test], self.target, self.names)
            following = _merge([current, self.block(stmt.body, head), *frame.continues])
            if following == current:
                return head
            current = following
        raise _Decline

    def simple(self, stmt: ast.stmt, state: _State) -> _State:
        target = self.target
        literal = _initial_mapping(stmt, target)
        if literal is not None:
            keys = _mapping_literal_keys(literal)
            return None if keys is None else frozenset(keys)
        if _rebinds([stmt], target):
            return None
        added = _keys_added(stmt, target, self.names)
        if added is None:
            raise _Decline
        return state | added if isinstance(state, frozenset) else state


def _value_of(ret: ast.Return | None) -> ast.expr | None:
    """What ``ret`` hands back; a one-element list stands for its element.

    Each item of a returned list is validated on its own, so ``return [out]`` is
    checked exactly as ``return out``.
    """
    if ret is None or ret.value is None:
        return None
    value = ret.value
    if isinstance(value, ast.List) and len(value.elts) == 1:
        element = value.elts[0]
        if not isinstance(element, ast.Starred):
            return element
    return value


def _returned_name_of(ret: ast.Return | None) -> str | None:
    value = _value_of(ret)
    return value.id if isinstance(value, ast.Name) else None


def _returned_name(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The name the tail return hands back, if it hands back a name."""
    return _returned_name_of(_last_return(func))


def _return_readings(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[ast.Return, frozenset[str]]]:
    """Each return some path reaches whose mapping's keys can be read, with those keys.

    Every return hands back a record to validate, not only the last. One handing back
    a mapping literal, or a name bound to one on every path to it, is read; one handing
    back nothing, a parameter, a helper's result, a ``**spread``, a longer list, or a
    name the walk cannot follow (a computed key, a return inside a loop) is left out,
    so it neither refuses nor excuses a key.
    """
    returns = list(_iter_own_returns(func))
    if not returns:
        return []
    reach = _OutputFlow()
    try:
        reach.block(func.body, None)
    except _Decline:
        return []
    readings: list[tuple[ast.Return, frozenset[str]]] = []
    by_name: dict[str, list[ast.Return]] = {}
    for ret in returns:
        if ret not in reach.reached:
            continue
        value = _value_of(ret)
        if isinstance(value, ast.Name):
            by_name.setdefault(value.id, []).append(ret)
        elif value is not None and _is_mapping_literal(value):
            keys = _mapping_literal_keys(value)
            if keys is not None:
                readings.append((ret, frozenset(keys)))
    for name, named in by_name.items():
        flow = _OutputFlow(name)
        try:
            flow.block(func.body, None)
        except _Decline:
            continue
        for ret in named:
            # Unknown when a path binds it to what a helper built, or never to a literal.
            state = _merge(flow.at_return.get(ret, []))
            if isinstance(state, frozenset):
                readings.append((ret, state))
    return sorted(readings, key=lambda reading: (reading[0].lineno, reading[0].col_offset))


def _unconditional_output_keys(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str] | None:
    """The constant string keys every readable return of the UDF hands back.

    Returns None when no return can be read (a scalar or longer list return, a
    helper-call initialiser, a ``**spread``, a key removed by a computed name, a
    return inside a loop, etc.). None means "decline to decide" — the caller emits no
    warning.
    """
    readings = _return_readings(func)
    if not readings:
        return None
    return set(frozenset.intersection(*(keys for _ret, keys in readings)))


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
    """One finding per required schema field some readable return of a kind:tool
    UDF hands back without (see ``_return_readings``).

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
        readings = _return_readings(func)
        for field in required:
            lacking = [ret for ret, keys in readings if field not in keys]
            if lacking:
                findings.append(_finding(name, func, field, info, lacking))
    return findings


def _finding(
    action: str,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    field: str,
    info: dict,
    lacking: list[ast.Return],
) -> str:
    """The refusal for ``field``, which each return in ``lacking`` hands back without."""
    tail = _last_return(func)
    if tail not in lacking:
        early = lacking[0]
        block = next((block for stmt, block in _statements(func.body, None) if stmt is early), None)
        how = f"returns without it at {_located(early.lineno, info)}" + (
            f", inside {block}" if block else ""
        )
        return (
            f"{action}: output schema requires '{field}' but the tool '{func.name}' {how}, "
            f"so a record that takes that path fails output validation at run time. Make "
            f"'{field}' optional in the schema, or set it on every path in the tool."
        )
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
