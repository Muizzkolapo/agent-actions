"""Config merge and initialization functions extracted from ActionExpander."""

import copy
from typing import Any

from agent_actions.errors import ConfigurationError
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


# The settings the chunker reads out of chunk_config, which are also writable as
# keys of their own on an action or in defaults.
CHUNK_SETTINGS = ("chunk_size", "chunk_overlap", "tokenizer_model", "split_method")


def process_chunk_config(
    agent: dict[str, Any], action: dict[str, Any], defaults: dict[str, Any]
) -> None:
    """Merge the chunk settings, name by name, later layers winning.

    Per name rather than per block, so a narrower block keeps the names it omits
    and a block written further out cannot overrule the action. The project
    file's settings arrive spread across the workflow's keys, outside all four.
    """
    layers = (
        {setting: defaults.get(setting) for setting in CHUNK_SETTINGS},
        defaults.get("chunk_config") or {},
        {setting: action.get(setting) for setting in CHUNK_SETTINGS},
        action.get("chunk_config") or {},
    )

    merged: dict[str, Any] = {}
    for layer in layers:
        for setting in CHUNK_SETTINGS:
            value = layer.get(setting)
            if value is not None:
                merged[setting] = value
    agent["chunk_config"] = merged
    _refuse_unsplittable(merged, action.get("name", "unknown"))


def _refuse_unsplittable(chunk_config: dict[str, Any], action_name: str) -> None:
    """Refuse at load the size/overlap pair the splitter refuses at split.

    Merging by name is what lets a nearer chunk_size meet an overlap set further
    out, so the pair is reachable without either level asking for it. Both values
    are known here; leaving it to the splitter spends a run to say so.
    """
    size = chunk_config.get("chunk_size")
    overlap = chunk_config.get("chunk_overlap")
    size = get_default("chunk_size") if size is None else size
    overlap = get_default("chunk_overlap") if overlap is None else overlap
    split_method = chunk_config.get("split_method") or get_default("split_method")

    if overlap >= size and split_method in ("tiktoken", "chars"):
        raise ConfigurationError(
            f"chunk_overlap ({overlap}) must be smaller than chunk_size ({size}) "
            f"for a '{split_method}' split",
            context={
                "action": action_name,
                "chunk_size": size,
                "chunk_overlap": overlap,
                "split_method": split_method,
            },
        )


def initialize_optional_fields(agent: dict[str, Any]) -> None:
    """Initialize optional fields in agent configuration."""
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
