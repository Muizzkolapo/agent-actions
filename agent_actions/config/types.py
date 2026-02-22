"""Type definitions for agent configuration structures."""

from typing import TypedDict, Optional, List, Dict, Any


class ContextScopeDict(TypedDict, total=False):
    """Context scope configuration for field flow control."""

    observe: List[str]
    passthrough: List[str]
    drop: List[str]
    keep: List[str]
    seed_data: Dict[str, Any]
    static_data: Dict[str, Any]


class GuardConfigDict(TypedDict, total=False):
    """Guard condition for conditional action execution.

    Supports two formats:
    - New format: clause/scope/behavior (e.g., {"clause": "...", "behavior": "skip"})
    - Legacy format: field/operator/value (e.g., {"field": "x", "operator": ">", "value": 0.8})
    """

    # New format
    clause: str
    scope: str  # "item" | "agent"
    behavior: str  # "skip" | "filter"
    passthrough_on_error: bool
    passthrough_on_empty: bool

    # Legacy format
    field: str
    operator: str
    value: Any


class WhereClauseDict(TypedDict, total=False):
    """WHERE clause configuration for conditional filtering.

    Supports SQL-like expressions evaluated per-item or per-agent.
    See WhereClauseConfig (output/response/config_schema.py) for
    validation rules and defaults.
    """

    clause: str
    scope: str  # "item" | "agent"
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


class AgentConfigDict(TypedDict, total=False):
    """Fully-expanded agent configuration as used at runtime.

    Distinct from AgentEntryDict (raw YAML entry). This represents the
    post-expansion config flowing through workflow, processing, and LLM layers.

    Note: ``schema_file`` and ``prompt_file`` are pre-expansion YAML keys
    consumed by preflight validation only. They do not survive into the
    runtime config and therefore belong in AgentEntryDict, not here.

    ``data_source`` is a workflow-level default (``defaults.data_source``),
    stored on ``AgentRunner.data_source_config`` — not per-agent.

    Keys shared with AgentEntryDict (agent_type, name, model_vendor, etc.)
    are intentionally duplicated: AgentEntryDict represents raw YAML input,
    this type represents the post-expansion runtime shape. Changes to the
    YAML schema may require updates in both places.
    """

    # Identity
    agent_type: str
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
    run_mode: str  # "online" | "batch"
    granularity: str  # "record" | "file"
    is_operational: bool
    json_mode: bool
    output_field: str

    # Prompt & Schema
    prompt: str
    schema_name: str
    schema: Dict[str, Any]
    compiled_schema: Dict[str, Any]
    json_output_schema: Dict[str, Any]
    prompt_debug: bool

    # Generation parameters
    temperature: float
    max_tokens: int

    # Dependencies & flow
    dependencies: List[str]
    chunk_config: Dict[str, Any]
    context_scope: ContextScopeDict

    # Guard / skip
    guard: GuardConfigDict
    conditional_clause: str
    skip_if: str
    skip_condition: str  # alternative to skip_if
    where_clause: WhereClauseDict

    # Optional features
    ephemeral: bool
    add_dispatch: bool
    reprompt: Dict[str, Any]
    constraints: List[str]
    retry: Dict[str, Any]
    max_execution_time: int
    on_empty: str  # "warn" | "error" | "skip"

    # Anthropic-specific
    anthropic_version: str
    enable_prompt_caching: bool

    # Versioning
    is_versioned_agent: bool
    version_base_name: str
    _version_context: Dict[str, Any]  # runtime-injected versioning metadata
    version_consumption_config: Dict[str, Any]  # controls version iteration

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


class AgentEntryDict(TypedDict, total=False):
    """Typed representation of a single agent configuration entry (raw YAML).

    See AgentConfigDict for the post-expansion runtime shape. Keys shared
    between both types are intentionally duplicated to represent different
    pipeline stages.
    """

    agent_type: str
    name: Optional[str]
    model_name: Optional[str]
    # Model vendor/provider: "openai", "gemini", "anthropic", "groq", or "tool"
    model_vendor: Optional[str]
    api_key: Optional[str]
    code_path: Optional[str]
    dependencies: List[str]
    prompt: Optional[str]
    schema_name: Optional[str]
    chunk_config: Dict[str, Any]
    is_operational: bool
    conditional_clause: Optional[str]
    where_clause: Optional[WhereClauseDict]
    skip_if: Optional[str]
    ephemeral: Optional[bool]
    add_dispatch: Optional[bool]
    # Anthropic-specific configuration options
    # API version header for Anthropic requests (e.g., "2023-06-01")
    anthropic_version: Optional[str]
    # Enable Anthropic's prompt caching feature for improved performance
    enable_prompt_caching: Optional[bool]
    # Control field flow: observe (LLM context), drop (block), passthrough (output)
    context_scope: Optional[ContextScopeDict]
    # HITL config (assigned by expander for kind="hitl" agents)
    hitl: Optional[HitlConfigDict]


# Alias for the list of agent entries under a pipeline name
AgentConfigList = List[AgentEntryDict]

# Alias for the mapping of pipeline/agent name to its configuration list
AgentConfigMap = Dict[str, AgentConfigList]
