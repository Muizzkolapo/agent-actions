"""Preflight check: a tool consumer's required output must be guaranteed by an
upstream producer's schema or declared as synthesized via `defaults:`. Symmetric
two-level descent on both sides (root, `field.`, `field[].`); no UDF source read."""

from __future__ import annotations

from typing import Any

_NESTED_DEPTH = 2


def _walk_required(node: Any, out: set[str], depth: int) -> None:
    """Collect `required` field names from every object node up to _NESTED_DEPTH.

    A dict with ``type: object`` contributes its ``required`` list at the
    current depth. A dict with ``type: array`` recurses one level into
    ``items``. Deeper descent is skipped. Non-dict nodes and unknown types
    are silently skipped so a partial schema does not raise.
    """
    if not isinstance(node, dict) or depth > _NESTED_DEPTH:
        return
    node_type = node.get("type")
    if node_type == "object":
        for field in node.get("required") or []:
            if isinstance(field, str):
                out.add(field)
        for prop_schema in (node.get("properties") or {}).values():
            _walk_required(prop_schema, out, depth + 1)
    elif node_type == "array":
        _walk_required(node.get("items") or {}, out, depth + 1)


def _required_fields_two_level(schema: dict[str, Any]) -> set[str]:
    """Set of field names required at any position within the depth window.
    Used for BOTH producer-guaranteed and consumer-required sides so the
    check is symmetric."""
    out: set[str] = set()
    _walk_required(schema, out, depth=0)
    return out


def _upstream_edges(
    consumer_name: str,
    consumer_config: dict[str, Any],
    action_configs: dict[str, dict[str, Any]],
) -> set[str]:
    """Every action name feeding this consumer.

    Includes explicit `dependencies` plus any producer named in
    `context_scope.observe` / `passthrough` entries (`<producer>.<field>` or
    `<producer>.*` shapes). Fan-out siblings sharing a `version_base_name`
    are resolved so a reference to the base name reaches every sibling.
    """
    edges: set[str] = set()

    deps = consumer_config.get("dependencies") or []
    if isinstance(deps, str):
        deps = [deps]
    for dep in deps:
        if isinstance(dep, str):
            edges.add(dep)

    context = consumer_config.get("context_scope") or {}
    if isinstance(context, dict):
        for kind in ("observe", "passthrough"):
            entries = context.get(kind) or []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, str):
                    continue
                head = entry.split(".", 1)[0].rstrip("*")
                if head and head != consumer_name:
                    edges.add(head)

    resolved: set[str] = set()
    for edge in edges:
        resolved.add(edge)
        for name, cfg in action_configs.items():
            if cfg.get("version_base_name") == edge:
                resolved.add(name)
    return resolved


def find_dag_schema_compatibility_gaps(
    action_configs: dict[str, dict[str, Any]],
) -> list[str]:
    """One finding per required output field on a tool consumer that is neither
    guaranteed by an upstream producer nor declared as synthesized via
    `defaults:` on the action.

    Warn-only for Phase 2 of spec 592. Phase 4 flips this fatal and removes
    the sibling `find_conditional_required_field_risks` scanner it subsumes.
    """
    findings: list[str] = []
    for consumer_name, consumer in action_configs.items():
        if consumer.get("kind") != "tool":
            continue

        output_schema = consumer.get("json_output_schema")
        if not isinstance(output_schema, dict):
            continue

        required_output = _required_fields_two_level(output_schema)
        if not required_output:
            continue

        defaults_raw = consumer.get("defaults") or {}
        defaults = set(defaults_raw.keys()) if isinstance(defaults_raw, dict) else set()
        implicit_inputs = required_output - defaults
        if not implicit_inputs:
            continue

        guaranteed: set[str] = set()
        for producer_name in _upstream_edges(consumer_name, consumer, action_configs):
            producer = action_configs.get(producer_name) or {}
            producer_schema = producer.get("json_output_schema")
            if isinstance(producer_schema, dict):
                guaranteed |= _required_fields_two_level(producer_schema)

        for field in sorted(implicit_inputs - guaranteed):
            findings.append(
                f"dag-fit: {consumer_name} output requires '{field}' but no upstream "
                f"producer guarantees it (declared in properties without being listed "
                f"as required), and no `defaults:` entry declares it synthesized on "
                f"this action. Runtime schema validation will reject records where the "
                f"UDF does not emit it. Fix one of: mark '{field}' optional in the "
                f"consumer schema; mark it required at the producing position upstream; "
                f"or add `defaults: {{{field}: <value>}}` on this action."
            )

    return findings
