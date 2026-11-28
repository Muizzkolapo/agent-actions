"""Config merge and initialization functions extracted from ActionExpander."""

import copy
import logging
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigurationError
from agent_actions.input.context.normalizer import split_optional_observe
from agent_actions.output.response.config_fields import get_default

logger = logging.getLogger(__name__)


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

    # Plain references on both sides: a mapping entry cannot be deduplicated, and one
    # field written `a.b` at one level and `a.b?` at the other is one field.
    defaults_scope = split_optional_observe(defaults_scope)
    action_scope = split_optional_observe(action_scope)
    merged = {**defaults_scope}

    for key, value in action_scope.items():
        if key in merged:
            merged[key] = merge_directive_value(merged[key], value)
        else:
            merged[key] = value

    return merged


def inherited_context_scope(
    action: dict[str, Any], defaults: dict[str, Any]
) -> dict[str, Any] | None:
    """The ``context_scope`` *action* gets: its own directives merged over the defaults'.

    A copy: the merge can return either level's dict as it is, and the loader adds
    an action's judged refs to its scope, which must not reach a sibling.
    """
    defaults_scope = defaults.get("context_scope")
    action_scope = action.get("context_scope")
    if not defaults_scope and not action_scope:
        return None
    return copy.deepcopy(deep_merge_context_scope(defaults_scope, action_scope))


# The settings the chunker reads out of chunk_config, which are also writable as
# keys of their own on an action or in defaults.
CHUNK_SETTINGS = ("chunk_size", "chunk_overlap", "tokenizer_model", "split_method")
# Read only out of a chunk_config block: as a loose key, `field` would mean anything.
SPLIT_FIELD = "field"


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
        for setting in (*CHUNK_SETTINGS, SPLIT_FIELD):
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

    if overlap >= size and split_method in ("tiktoken", "chars", "markdown"):
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


def _suite_rule_entries(suite: Any, project_root: Path | None) -> list[Any]:
    """The rules of a named suite; none without a root or when the suite does not load.

    Preflight and the run report a suite that does not load, each with its own message.
    """
    if project_root is None or not isinstance(suite, str):
        return []
    from agent_actions.expectations.loader import SuiteLoadError, load_schema_rules

    try:
        entries, _ = load_schema_rules(suite, project_root)
    except SuiteLoadError as exc:
        logger.debug("No judged context refs read from suite '%s': %s", suite, exc)
        return []
    return entries


def collect_judge_context_refs(
    expect: dict[str, Any] | None, schema: Any = None, project_root: Path | None = None
) -> list[str]:
    """The context: refs named by every llm_judge rule this action will run.

    Reads the rules the run reads, in its order: the named ``suite:`` (only when
    *project_root* is given), else the inline list, else the rules of the
    resolved schema, which is where the co-located form declares them. A merged
    block can hold both a suite and a list. A ref that is not a string is left
    for preflight to report.
    """
    # An empty dict is the bare block, not the absence of one — the runtime reads
    # the action's own schema for it, so its refs have to be observed as well.
    if expect is None:
        return []
    declared = expect.get("expectations")
    if expect.get("suite") is not None:
        entries = _suite_rule_entries(expect["suite"], project_root)
    elif isinstance(declared, list):
        entries = declared
    else:
        entries = _schema_rule_entries(expect, schema)
    refs: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "llm_judge":
            continue
        params = entry.get("params")
        context = params.get("context") if isinstance(params, dict) else None
        if isinstance(context, list):
            refs.extend(ref for ref in context if isinstance(ref, str))
    return refs


def observe_judge_context_refs(agent: dict[str, Any], refs: list[str]) -> None:
    """Union *refs* into the agent's observe, so dependency inference reads the source action."""
    if refs:
        scope = agent.get("context_scope") or {}
        agent["context_scope"] = {
            **scope,
            "observe": merge_directive_value(scope.get("observe", []), refs),
        }


def observe_suite_judge_context_refs(
    agents: list[dict[str, Any]], project_root: Path | None
) -> None:
    """Observe the judged context refs of each agent's named suite.

    The expander adds every other form's refs. A suite loads from the project
    root, which the expander does not have, so the loader calls this after it.
    """
    for agent in agents:
        expect = agent.get("expect")
        if isinstance(expect, dict) and expect.get("suite") is not None:
            refs = collect_judge_context_refs(expect, agent.get("schema"), project_root)
            observe_judge_context_refs(agent, refs)


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


def layered_defaults(outer: dict[str, Any], inner: dict[str, Any]) -> dict[str, Any]:
    """*inner*'s defaults over *outer*'s, each key merged as an action merges over defaults.

    ``context_scope``, ``expect`` and ``vendor_params`` merge key by key, and the chunk
    settings name by name, so an inner value wins whichever spelling either level uses.
    Every other key is replaced.
    """
    merged = {**outer, **inner}
    if outer.get("context_scope") or inner.get("context_scope"):
        merged["context_scope"] = deep_merge_context_scope(
            outer.get("context_scope"), inner.get("context_scope")
        )
    for key, merge in (("expect", merge_expect), ("vendor_params", merge_vendor_params)):
        value = merge(outer.get(key), inner.get(key))
        if value is not None:
            merged[key] = value
    if inner.get("chunk_config") or any(inner.get(name) is not None for name in CHUNK_SETTINGS):
        chunk: dict[str, Any] = {}
        for level in (outer, inner):
            for layer in (
                {name: level.get(name) for name in CHUNK_SETTINGS},
                level.get("chunk_config") or {},
            ):
                chunk.update(
                    {name: layer[name] for name in CHUNK_SETTINGS if layer.get(name) is not None}
                )
        merged["chunk_config"] = chunk
    return merged


def merge_vendor_params(base: Any, override: Any) -> dict[str, Any] | None:
    """*override*'s ``vendor_params`` over *base*'s, key by key; ``None`` when neither has any."""
    base = base if isinstance(base, dict) else None
    override = override if isinstance(override, dict) else None
    if base is None and override is None:
        return None
    return {**copy.deepcopy(base or {}), **copy.deepcopy(override or {})}
