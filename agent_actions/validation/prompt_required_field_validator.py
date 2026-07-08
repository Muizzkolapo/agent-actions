"""Flag prompt refs to schema fields the producing action does not mark required."""

from __future__ import annotations

import logging

from jinja2 import Environment, nodes
from jinja2.exceptions import TemplateSyntaxError

from agent_actions.utils.template_escape import escape_jinja_in_inline_code

logger = logging.getLogger(__name__)

# Roots that are Jinja builtins / the implicit loop var — never producing actions.
_NON_ACTION_ROOTS = frozenset(
    {"loop", "range", "dict", "lipsum", "cycler", "joiner", "namespace", "true", "false", "none"}
)

_ENV = Environment()


def _chain_root_and_field(node: nodes.Node) -> tuple[str, str] | None:
    """Return (root, first_field) for an attribute/subscript chain, else None.

    ``producer.b`` and ``producer["b"].x`` both yield ``("producer", "b")``.
    Non-string subscripts (int/dynamic keys) and chains not rooted in a plain
    name yield None.
    """
    attrs: list[str | None] = []
    current: nodes.Node = node
    while isinstance(current, nodes.Getattr | nodes.Getitem):
        if isinstance(current, nodes.Getattr):
            attrs.append(current.attr)
        elif isinstance(current.arg, nodes.Const) and isinstance(current.arg.value, str):
            attrs.append(current.arg.value)
        else:
            attrs.append(None)
        current = current.node
    if not isinstance(current, nodes.Name) or not attrs:
        return None
    attrs.reverse()
    if attrs[0] is None:
        return None
    return current.name, attrs[0]


def _target_names(target: nodes.Node) -> set[str]:
    """Loop-target names introduced by a ``{% for %}`` (locals, not refs)."""
    if isinstance(target, nodes.Name):
        return {target.name}
    if isinstance(target, nodes.Tuple):
        return {item.name for item in target.items if isinstance(item, nodes.Name)}
    return set()


def _guard_keys(test: nodes.Node) -> set[str]:
    """``root.field`` keys named by an ``{% if %}`` test — the fields it guards."""
    keys: set[str] = set()
    for sub in test.find_all((nodes.Getattr, nodes.Getitem)):
        ref = _chain_root_and_field(sub)
        if ref:
            keys.add(f"{ref[0]}.{ref[1]}")
    return keys


def _collect(
    node: nodes.Node, guarded: frozenset[str], locals_: frozenset[str], found: set
) -> None:
    """Record an outermost chain ref as unguarded unless its field is guarded."""
    ref = _chain_root_and_field(node)
    if ref and ref[0] not in locals_ and ref[0] not in _NON_ACTION_ROOTS:
        if f"{ref[0]}.{ref[1]}" not in guarded:
            found.add(ref)


def _walk(node: nodes.Node, guarded: frozenset[str], locals_: frozenset[str], found: set) -> None:
    """Walk the AST, flagging unconditional refs; ``{% if %}`` bodies gain the
    guarantees named by their own test (elif/else branches do not)."""
    if isinstance(node, nodes.If):
        body_guarded = guarded | _guard_keys(node.test)
        for child in node.body:
            _walk(child, body_guarded, locals_, found)
        for elif_node in node.elif_:
            _walk(elif_node, guarded, locals_, found)
        for child in node.else_:
            _walk(child, guarded, locals_, found)
        return
    if isinstance(node, nodes.For):
        _collect(node.iter, guarded, locals_, found)
        inner = locals_ | _target_names(node.target)
        for child in list(node.body) + list(node.else_):
            _walk(child, guarded, inner, found)
        return
    if isinstance(node, nodes.Macro):
        inner = locals_ | {a.name for a in node.args if isinstance(a, nodes.Name)}
        for child in node.body:
            _walk(child, guarded, inner, found)
        return
    if isinstance(node, nodes.Getattr | nodes.Getitem):
        _collect(node, guarded, locals_, found)
        return
    for child in node.iter_child_nodes():
        _walk(child, guarded, locals_, found)


def _unguarded_refs(template: str) -> set[tuple[str, str]]:
    """Return the ``(root, field)`` refs used outside any guarding ``{% if %}``."""
    try:
        ast = _ENV.parse(escape_jinja_in_inline_code(template))
    except TemplateSyntaxError as exc:
        logger.debug("Skipping prompt scan (syntax error): %s", exc)
        return set()
    found: set[tuple[str, str]] = set()
    _walk(ast, frozenset(), frozenset(), found)
    return found


def _optional_field_names(schema: dict) -> set[str]:
    """Names the producer declares but does not mark required."""
    return {f["id"] for f in schema.get("fields", []) if "id" in f and not f.get("required", False)}


def find_unguarded_required_refs(prompts: dict[str, str], schemas: dict[str, dict]) -> list[str]:
    """Return findings for unguarded prompt refs to non-required producer fields.

    A ref ``ns.field`` is flagged when ``ns`` has a producing schema, ``field``
    is declared by that schema but not marked required, and the ref is not inside
    the body of an ``{% if %}`` that guards ``ns.field``. Refs to an unknown
    namespace, to a field the schema does not declare, or to the action's own
    output namespace belong to other checks and are left alone here.
    """
    if not prompts or not schemas:
        return []
    optional_by_ns = {ns: _optional_field_names(schema) for ns, schema in schemas.items()}
    findings: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for action_name, template in prompts.items():
        for ns, field in sorted(_unguarded_refs(template)):
            if ns == action_name or field not in optional_by_ns.get(ns, frozenset()):
                continue
            key = (action_name, ns, field)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                f"{action_name}: prompt references '{ns}.{field}' but producer '{ns}' "
                f"does not guarantee '{field}' (declared without required: true, and "
                f"no if-guard protects the ref)"
            )
    return findings
