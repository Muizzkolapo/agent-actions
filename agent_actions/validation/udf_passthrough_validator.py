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


def _first_param(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The UDF's first positional parameter — the bus/record the framework passes in."""
    args = func.args
    params = list(args.posonlyargs) + list(args.args)
    if params:
        return params[0].arg
    return args.vararg.arg if args.vararg else None


def _is_sequence_index(sl: ast.AST) -> bool:
    """True for a slice or a (possibly negative) integer index — sequence access, not a mapping key."""
    if isinstance(sl, ast.Slice):
        return True
    if isinstance(sl, ast.Constant) and isinstance(sl.value, int):
        return True
    return (
        isinstance(sl, ast.UnaryOp)
        and isinstance(sl.operand, ast.Constant)
        and isinstance(sl.operand.value, int)
    )


def _reads_input(node: ast.AST, root: str, tainted: set[str]) -> bool:
    """True for a mapping read ``x.get(...)`` / ``x['key']`` where ``x`` is the input or derived.

    Numeric/slice subscripts are sequence access (string/list indexing) and are
    not mapping reads, so a string-first-param helper doing ``s[0]`` is not flagged.
    """
    if isinstance(node, ast.Subscript):
        if _is_sequence_index(node.slice):
            return False
        return _is_input(node.value, root, tainted)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
    ):
        return _is_input(node.func.value, root, tainted)
    return False


def _is_input(node: ast.AST, root: str, tainted: set[str]) -> bool:
    """True if *node* is the input parameter itself or a value already read from it."""
    if isinstance(node, ast.Name):
        return node.id == root or node.id in tainted
    return _reads_input(node, root, tainted)


def _is_derived(node: ast.AST, root: str, tainted: set[str]) -> bool:
    """True if *node* carries bus data through unchanged (opaque keys), not a fresh literal.

    A read off a *key* of the input is derived; the bare input parameter is not —
    returning the whole input is a filter whose keys already match its own schema.
    Dict/list literals and calls to other functions are construction boundaries.
    """
    if _reads_input(node, root, tainted):
        return True
    if isinstance(node, ast.Name):
        return node.id in tainted
    if isinstance(node, ast.IfExp):
        return _is_derived(node.body, root, tainted) or _is_derived(node.orelse, root, tainted)
    if isinstance(node, ast.BoolOp):
        return any(_is_derived(v, root, tainted) for v in node.values)
    if isinstance(node, ast.BinOp):
        return _is_derived(node.left, root, tainted) or _is_derived(node.right, root, tainted)
    if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
        local = set(tainted)
        for gen in node.generators:
            if _is_derived(gen.iter, root, local):
                local |= _target_names(gen.target)
        return _is_derived(node.elt, root, local)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_is_derived(elt, root, tainted) for elt in node.elts)
    return False


def _bus_tainted_names(func: ast.AST, root: str) -> set[str]:
    """Local names holding bus-derived values, to a fixpoint over the function body."""
    tainted: set[str] = set()
    while True:
        before = len(tainted)
        for node in ast.walk(func):
            if isinstance(node, ast.For) and _is_derived(node.iter, root, tainted):
                tainted |= _target_names(node.target)
            elif isinstance(node, ast.comprehension) and _is_derived(node.iter, root, tainted):
                tainted |= _target_names(node.target)
            elif isinstance(node, ast.Assign) and _is_derived(node.value, root, tainted):
                for tgt in node.targets:
                    tainted |= _target_names(tgt)
            elif (
                isinstance(node, (ast.AnnAssign, ast.NamedExpr))
                and node.value is not None
                and _is_derived(node.value, root, tainted)
            ):
                tainted |= _target_names(node.target)
        if len(tainted) == before:
            return tainted


def _bus_accumulators(func: ast.AST, root: str, tainted: set[str]) -> set[str]:
    """Names fed bus-derived items via append/extend/+= — candidate output lists."""
    accs: set[str] = set()
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("append", "extend")
            and isinstance(node.func.value, ast.Name)
            and node.args
            and _is_derived(node.args[0], root, tainted)
        ):
            accs.add(node.func.value.id)
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and _is_derived(node.value, root, tainted)
        ):
            accs.add(node.target.id)
    return accs


def _returns_passthrough(func: ast.AST, root: str) -> bool:
    """True if a bus-derived value is returned — directly, or as an accumulator of bus items.

    An accumulator fed bus data but only nested inside a constructed dict/other
    literal is never returned as an output item, so it is not flagged."""
    tainted = _bus_tainted_names(func, root)
    reachable = tainted | _bus_accumulators(func, root, tainted)
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None:
            if _is_derived(node.value, root, reachable):
                return True
    return False


def _source_is_passthrough(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for func in ast.walk(tree):
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            root = _first_param(func)
            if root and _returns_passthrough(func, root):
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
