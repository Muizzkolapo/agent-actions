"""Preflight check: a tool's required output fields must be ones its UDF returns.

A tool's output is validated exactly as the UDF returns it. Upstream fields
reach the tool as input, keyed by action name, and `context_scope.passthrough`
fields are added beside its output after validation, so neither supplies a
field the tool leaves out. The caller reads the UDF source and passes the root
keys each tool provably returns as `synthesized`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DAG_FIT_REMEDY = (
    "return the field from the tool on every path, or mark it optional in the tool's "
    "output schema — the tool's output is validated exactly as it returns it, so a "
    "field upstream or in `passthrough:` does not count. If the tool does return it "
    "in a way this check cannot read, declare it with `defaults:` on the action."
)


def find_dag_schema_compatibility_gaps(
    action_configs: dict[str, dict[str, Any]],
    synthesized: Mapping[str, set[str] | None] | None = None,
) -> dict[str, list[str]]:
    """Per tool action, the required root output fields its UDF does not provably
    return, as ``{action: [sorted missing fields]}``.

    ``synthesized`` maps an action to the root keys its UDF provably returns; an
    action absent from it is read as returning none. ``None`` for an action means
    its output keys could not be read, so it is not checked. A field declared in
    the action's ``defaults:`` is taken as returned. Fields nested inside a root
    key are not checked: the tool computes a key it returns whole, and a key it
    does not return is reported itself when required, or never checked when not.
    """
    synthesized = synthesized or {}
    gaps: dict[str, list[str]] = {}
    for name, config in action_configs.items():
        if config.get("kind") != "tool":
            continue
        if name in synthesized and synthesized[name] is None:
            continue
        returned = synthesized.get(name) or set()

        output_schema = config.get("json_output_schema")
        if not isinstance(output_schema, dict) or output_schema.get("type") != "object":
            continue
        required = {f for f in output_schema.get("required") or [] if isinstance(f, str)}

        defaults_raw = config.get("defaults") or {}
        declared = set(defaults_raw.keys()) if isinstance(defaults_raw, dict) else set()

        missing = sorted(required - returned - declared)
        if missing:
            gaps[name] = missing
    return gaps
