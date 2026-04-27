"""Type definitions for action configuration structures."""

from enum import Enum
from typing import Any, TypedDict


class Granularity(str, Enum):
    """Granularity levels for action execution."""

    RECORD = "record"
    FILE = "file"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            lower = value.lower()
            for member in cls:
                if member.value == lower:
                    return member
        return None


class RunMode(str, Enum):
    """Execution run modes for agent processing."""

    ONLINE = "online"
    BATCH = "batch"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            lower = value.lower()
            for member in cls:
                if member.value == lower:
                    return member
        return None


class ContextScopeDict(TypedDict, total=False):
    """Context scope configuration for field flow control."""

    observe: list[str]
    passthrough: list[str]
    drop: list[str]
    keep: list[str]
    seed_path: dict[str, Any]
    static_data: dict[str, Any]


class GuardConfigDict(TypedDict, total=False):
    """Guard condition for conditional action execution.

    Primary format: condition/on_false (e.g., {"condition": "score >= 85", "on_false": "filter"})
    """

    condition: str
    on_false: str  # "skip" | "filter"
    passthrough_on_error: bool
    passthrough_on_empty: bool


class WhereClauseDict(TypedDict, total=False):
    """WHERE clause configuration for conditional filtering.

    Supports SQL-like expressions evaluated per-item or per-action.
    See WhereClauseConfig (output/response/config_schema.py) for
    validation rules and defaults.
    """

    clause: str
    scope: str  # "item" | "action"
    behavior: str  # "skip" | "filter"
    passthrough_on_empty: bool
    passthrough_on_error: bool
    cache_enabled: bool


class HitlConfigDict(TypedDict, total=False):
    """Human-in-the-loop review configuration.

    See HitlConfig (config/schema.py) for validation rules and defaults.
    """

    port: int
    instructions: str
    timeout: int
    require_comment_on_reject: bool


class ActionConfigDict(TypedDict, total=False):
    """Fully-expanded action configuration as used at runtime.

    Distinct from ActionEntryDict (raw YAML entry). This represents the
    post-expansion config flowing through workflow, processing, and LLM layers.

    Note: ``schema_file`` and ``prompt_file`` are pre-expansion YAML keys
    consumed by preflight validation only. They do not survive into the
    runtime config and therefore belong in ActionEntryDict, not here.

    ``data_source`` is a workflow-level default (``defaults.data_source``),
    stored on ``ActionRunner.data_source_config`` — not per-action.

    Keys shared with ActionEntryDict (agent_type, name, model_vendor, etc.)
    are intentionally duplicated: ActionEntryDict represents raw YAML input,
    this type represents the post-expansion runtime shape. Changes to the
    YAML schema may require updates in both places.
    """

    # Identity
    agent_type: str
    action_name: str  # runtime-injected by executor for batch namespacing
    name: str
    kind: str  # "llm" | "tool" | "hitl"

    # Model
    model_vendor: str
    model_name: str
    model: str  # legacy fallback for model_name
    api_key: str  # env var reference
    gemini_api_key: str  # vendor-specific API key override
    openai_api_key: str  # vendor-specific API key override
    base_url: str

    # Execution
    run_mode: RunMode  # RunMode.ONLINE | RunMode.BATCH
    granularity: str  # "record" | "file"
    is_operational: bool
    json_mode: bool
    output_field: str

    # Prompt & Schema
    prompt: str
    schema_name: str
    schema: dict[str, Any]
    json_output_schema: dict[str, Any]
    prompt_debug: bool

    # Generation parameters
    temperature: float
    max_tokens: int

    # Dependencies & flow
    dependencies: list[str]
    chunk_config: dict[str, Any]
    context_scope: ContextScopeDict

    # Guard / skip
    guard: GuardConfigDict
    conditional_clause: str
    skip_if: str
    skip_condition: str  # alternative to skip_if
    where_clause: WhereClauseDict

    # Optional features
    add_dispatch: bool
    reprompt: dict[str, Any]
    constraints: list[str]
    retry: dict[str, Any]
    max_execution_time: int
    on_empty: str  # "warn" | "error" | "skip"

    # Anthropic-specific
    anthropic_version: str
    enable_prompt_caching: bool

    # Versioning
    is_versioned_agent: bool
    version_base_name: str
    _version_context: dict[str, Any]  # runtime-injected versioning metadata
    version_consumption_config: dict[str, Any]  # controls version iteration

    # Runtime-injected by coordinator (subscript-assigned)
    idx: int
    workflow_config_path: str
    workflow_session_id: str

    # Tool / code paths
    tools_path: str
    tool_path: str  # alternative tool path (distinct from tools_path)
    tools: Any
    code_path: str

    # HITL-specific (subscript-assigned in pipeline.py)
    hitl: HitlConfigDict
    _hitl_state_dir: str
    _hitl_file_stem: str

    # Reduce/fan-in
    reduce_key: str
    primary_dependency: str

    # Batch
    batch_id: str


class ActionEntryDict(TypedDict, total=False):
    """Typed representation of a single action configuration entry (raw YAML).

    See ActionConfigDict for the post-expansion runtime shape. Keys shared
    between both types are intentionally duplicated to represent different
    pipeline stages.
    """

    agent_type: str
    name: str | None
    model_name: str | None
    # Model vendor/provider: "openai", "gemini", "anthropic", "groq", or "tool"
    model_vendor: str | None
    api_key: str | None
    code_path: str | None
    dependencies: list[str]
    prompt: str | None
    schema_name: str | None
    chunk_config: dict[str, Any]
    is_operational: bool
    conditional_clause: str | None
    where_clause: WhereClauseDict | None
    skip_if: str | None
    add_dispatch: bool | None
    # Anthropic-specific configuration options
    # API version header for Anthropic requests (e.g., "2023-06-01")
    anthropic_version: str | None
    # Enable Anthropic's prompt caching feature for improved performance
    enable_prompt_caching: bool | None
    # Control field flow: observe (LLM context), drop (block), passthrough (output)
    context_scope: ContextScopeDict | None
    # HITL config (assigned by expander for kind="hitl" actions)
    hitl: HitlConfigDict | None


# Alias for the list of action entries under a pipeline name
ActionConfigList = list[ActionEntryDict]

# Alias for the mapping of pipeline/agent name to its configuration list
ActionConfigMap = dict[str, ActionConfigList]
