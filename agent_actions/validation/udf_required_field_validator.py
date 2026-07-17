"""Static-AST check: a kind:tool UDF must unconditionally produce every
required output-schema field, or the runtime schema validator will reject a
subset of records mid-run.

The runtime signal we mirror is `_validate_udf_output` in
``agent_actions/utils/udf_management/tooling.py``: `jsonschema.validate` on
each returned item against ``json_output_schema``, which raises
``SchemaValidationError`` when a `required` property is missing. Post-568
every flat schema field is required by default, so a UDF that emits a field
only when a guard passes crashes the workflow whenever the guard misses.

This validator finds the shape statically. It never imports or executes the
UDF — only its source is inspected. It errs toward silence: any construction
shape it does not fully recognise is treated as "unknown" and produces no
warning, so the check contributes zero false positives on tools that do emit
their required fields unconditionally.
"""

from __future__ import annotations

import ast


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


def _last_return(func: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Return | None:
    """The tail return, chosen by source order — early guard returns must not shadow it.

    ``ast.walk`` yields in BFS order, so we sort by lineno to get the tail
    return (the return that actually determines the output shape in the happy
    path). This mirrors how a reader thinks about a function whose top starts
    with `if not isinstance(data, dict): return data`.
    """
    returns = [
        node for node in ast.walk(func) if isinstance(node, ast.Return) and node.value is not None
    ]
    if not returns:
        return None
    return max(returns, key=lambda r: r.lineno)


def _unconditional_output_keys(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str] | None:
    """The constant string keys the UDF puts on its returned mapping without any guard.

    Returns None when the returned shape is unrecognisable (list/scalar return,
    a helper-call initialiser, a ``**spread`` in the returned literal, etc.).
    None means "decline to decide" — the caller emits no warning."""
    ret = _last_return(func)
    if ret is None or ret.value is None:
        return None
    # `return {...}` — the literal's constant keys are the unconditional set.
    if isinstance(ret.value, ast.Dict):
        if _has_spread(ret.value):
            return None
        return _const_str_keys(ret.value)
    # `return name` — walk the function's TOP-LEVEL body only. Anything nested
    # in if/for/while/try/with is by definition conditional.
    if not isinstance(ret.value, ast.Name):
        return None
    target = ret.value.id
    keys: set[str] = set()
    initial_found = False
    for stmt in func.body:
        # target = {...}
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == target
            and isinstance(stmt.value, ast.Dict)
        ):
            if _has_spread(stmt.value):
                return None
            keys |= _const_str_keys(stmt.value)
            initial_found = True
            continue
        # target["k"] = ...
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Subscript)
            and isinstance(stmt.targets[0].value, ast.Name)
            and stmt.targets[0].value.id == target
            and isinstance(stmt.targets[0].slice, ast.Constant)
            and isinstance(stmt.targets[0].slice.value, str)
        ):
            keys.add(stmt.targets[0].slice.value)
            continue
        # target.update({...})
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "update"
            and isinstance(stmt.value.func.value, ast.Name)
            and stmt.value.func.value.id == target
            and stmt.value.args
            and isinstance(stmt.value.args[0], ast.Dict)
        ):
            if _has_spread(stmt.value.args[0]):
                return None
            keys |= _const_str_keys(stmt.value.args[0])
            continue
    if not initial_found:
        # No dict-literal initial assignment (e.g. `result = build(data)` or
        # `result = data.copy()`): we cannot enumerate what the helper puts
        # in, so declining is safer than flagging every required field.
        return None
    return keys


def find_conditional_required_field_risks(actions: dict[str, dict]) -> list[str]:
    """One warning per required schema field a kind:tool UDF cannot statically be
    shown to emit unconditionally.

    Each action entry provides:

    - ``source``: UDF text (as returned by ``inspect.getsource``).
    - ``required``: the compiled ``json_output_schema.required`` list.
    - ``additional_properties``: recorded for parity with the sibling
      passthrough validator, but does not weaken the check — allowing extra
      keys does not make a missing required key permissible.
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
        emitted: set[str] | None = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                emitted = _unconditional_output_keys(node)
                break
        if emitted is None:
            continue
        for field in required:
            if field not in emitted:
                findings.append(
                    f"{name}: output schema requires '{field}' but the UDF does not "
                    f"unconditionally emit it — the field is only written inside a "
                    f"conditional / dynamic-key branch. Runtime schema validation "
                    f"will reject any record whose branch does not fire. Add "
                    f"`optional: true` to '{field}' in the schema, or emit it "
                    f"unconditionally in the UDF."
                )
    return findings
