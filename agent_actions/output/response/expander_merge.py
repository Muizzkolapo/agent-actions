"""Config merge and initialization functions extracted from ActionExpander."""

import copy
from typing import Any

from agent_actions.output.response.config_fields import get_default


def merge_directive_value(existing: Any, new_value: Any) -> Any:
    """Merge two directive values based on their types."""
    if isinstance(existing, dict) and isinstance(new_value, dict):
        return {**existing, **new_value}
    if isinstance(existing, list) and isinstance(new_value, list):
        return list(dict.fromkeys(existing + new_value))
    return new_value


def deep_merge_context_scope(
    defaults_scope: dict[str, Any] | None, action_scope: dict[str, Any] | None
) -> dict[str, Any]:
    """
    Deep merge context_scope directives from defaults and action levels.

    Action-level directives are merged with (not replace) defaults directives.
    This allows actions to define drop/observe while inheriting seed from defaults.
    """
    if not defaults_scope:
        return action_scope or {}
    if not action_scope:
        return defaults_scope or {}

    merged = {**defaults_scope}

    for key, value in action_scope.items():
        if key in merged:
            merged[key] = merge_directive_value(merged[key], value)
        else:
            merged[key] = value

    return merged


def process_chunk_config(
    agent: dict[str, Any], action: dict[str, Any], defaults: dict[str, Any]
) -> None:
    """Process chunk configuration for an agent."""
    chunk_config = action.get("chunk_config", defaults.get("chunk_config", {}))
    if chunk_config:
        agent["chunk_config"] = chunk_config
    else:
        agent["chunk_config"] = {}
        if action.get("chunk_size") or defaults.get("chunk_size"):
            agent["chunk_config"]["chunk_size"] = action.get(
                "chunk_size", defaults.get("chunk_size", get_default("chunk_size"))
            )
        if action.get("chunk_overlap") or defaults.get("chunk_overlap"):
            agent["chunk_config"]["chunk_overlap"] = action.get(
                "chunk_overlap", defaults.get("chunk_overlap", get_default("chunk_overlap"))
            )


def initialize_optional_fields(agent: dict[str, Any]) -> None:
    """Initialize optional fields in agent configuration."""
    agent.setdefault("skip_if", None)
    agent.setdefault("add_dispatch", None)
    agent.setdefault("conditional_clause", None)
    agent.setdefault("guard", None)


def _schema_rule_entries(expect: dict[str, Any], schema: Any) -> list[Any]:
    """The rules of the action's own schema, when the expect block defaults to them."""
    if expect.get("suite") is not None or not isinstance(schema, dict):
        return []
    from agent_actions.expectations.loader import schema_rule_entries

    try:
        entries, _ = schema_rule_entries(str(schema.get("name") or "schema"), schema)
    except ValueError:
        return []
    return entries


def collect_judge_context_refs(expect: dict[str, Any] | None, schema: Any = None) -> list[str]:
    """The context: refs named by every llm_judge rule this action will run.

    Reads the action's inline list, or — when it has none — the rules of its
    resolved schema, which is where the co-located form declares them. A named
    ``suite:`` is still out of reach here: it needs a project root this layer
    does not have.
    """
    # An empty dict is the bare block, not the absence of one — the runtime reads
    # the action's own schema for it, so its refs have to be observed as well.
    if expect is None:
        return []
    declared = expect.get("expectations")
    entries = declared if isinstance(declared, list) else _schema_rule_entries(expect, schema)
    refs: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "llm_judge":
            continue
        params = entry.get("params")
        context = params.get("context") if isinstance(params, dict) else None
        if isinstance(context, list):
            refs.extend(context)
    return refs


def _cannot_repair(agent: dict[str, Any]) -> bool:
    """Whether regenerating this action's output is meaningless.

    Re-running a deterministic tool yields the same output, and one
    file-granularity call produces every record, so a single failing record
    would regenerate all of them.
    """
    from agent_actions.processing.helpers import _is_tool_action

    granularity = agent.get("granularity")
    return _is_tool_action(agent) or str(granularity or "").lower() == "file"


def adapt_inherited_expect(
    merged: dict[str, Any] | None,
    action_expect: Any,
    agent: dict[str, Any],
) -> dict[str, Any] | None:
    """Bend the parts of *merged* the action did not ask for to suit the action.

    A workflow-wide block is a statement about the workflow, and a real workflow
    mixes LLM actions with tools and file writers. Applying an inherited policy
    to an action that cannot honour it would make one defaults line unusable on
    every real config. A policy the author wrote on the action is left alone —
    it is a decision, and preflight is where a wrong one is reported.
    """
    if merged is None:
        return None
    own = action_expect if isinstance(action_expect, dict) else {}
    result = dict(merged)

    if "repair" not in own and _cannot_repair(agent):
        # Rules still say something true about a tool's output, so they stay and
        # stop repairing. A block with no rules had nothing but the policy.
        if result.get("expectations") is None and result.get("suite") is None:
            return None
        result["repair"] = "none"

    if result.get("repair") == "none" and "structural" not in own:
        # Nothing regenerates, so an inherited structural mode describes nothing.
        result.pop("structural", None)

    return result


def merge_expect(defaults: Any, action: Any) -> dict[str, Any] | None:
    """The action's ``expect:`` block over the workflow's, key by key.

    Key by key rather than whole-value, because the block holds two decisions
    made at different levels: the repair policy is a workflow-wide choice, and
    the rules belong to one action. Replacing would mean an action that adds a
    rule silently returns to the default policy.

    A non-mapping on either side is ignored here; ``ExpectConfig`` refuses it
    with a message about the block, which is the better error.
    """
    base = defaults if isinstance(defaults, dict) else None
    override = action if isinstance(action, dict) else None
    if base is None and override is None:
        return None
    # An empty dict is the bare block — "read my own schema" — so it survives
    # the merge as a block rather than collapsing to no block at all.
    return {**copy.deepcopy(base or {}), **copy.deepcopy(override or {})}
