"""Schema definitions for the new workflow format."""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_actions.output.response.guard_parser import GuardParser
from agent_actions.output.response.consolidated_guard import parse_guard_config


class ActionKind(str, Enum):
    """Types of actions in the workflow."""

    LLM = "llm"
    TOOL = "tool"
    HITL = "hitl"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            lower = value.lower()
            for member in cls:
                if member.value == lower:
                    return member
        return None


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


class VersionMode(str, Enum):
    """Version execution modes."""

    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            lower = value.lower()
            for member in cls:
                if member.value == lower:
                    return member
        return None


class VersionConfig(BaseModel):
    """Configuration for version-based actions."""

    param: str = Field(default="i", description="Parameter name for version variable")
    range: List[int] = Field(  # noqa: A003 — shadows builtin; rename breaks YAML compat
        ..., description="Range of values for version parameter"
    )
    mode: VersionMode = Field(default=VersionMode.PARALLEL, description="Execution mode")


class MergePattern(str, Enum):
    """Patterns for version output consumption."""

    MERGE = "merge"
    MATCH = "match"


class VersionConsumptionConfig(BaseModel):
    """Configuration for consuming version outputs."""

    source: str = Field(..., description="Base name of the version action to consume")
    pattern: MergePattern = Field(
        default=MergePattern.MERGE, description="Pattern for merging version outputs"
    )


class RetryConfig(BaseModel):
    """Configuration for retry behavior on transport-layer failures."""

    enabled: bool = Field(default=True, description="Whether retry is enabled")
    max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of retry attempts (1-10)",
    )
    on_exhausted: Literal["return_last", "raise"] = Field(
        default="return_last",
        description="Behavior when max_attempts exhausted: return_last or raise",
    )


class RepromptConfig(BaseModel):
    """Configuration for reprompt behavior on validation failures.

    ``validation`` is optional when an external validator is provided
    (e.g. via ``on_schema_mismatch: reprompt``).
    """

    validation: Optional[str] = Field(default=None, description="Name of validation UDF function")
    max_attempts: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum number of reprompt attempts (1-10)",
    )
    on_exhausted: Literal["return_last", "raise"] = Field(
        default="return_last",
        description="Behavior when max_attempts exhausted: return_last or raise",
    )


class HitlConfig(BaseModel):
    """Configuration for Human-in-the-Loop actions."""

    port: int = Field(
        default=3001,
        ge=1024,
        le=65535,
        description="Port for approval UI server",
    )
    instructions: str = Field(
        ...,
        min_length=1,
        description="Instructions displayed to user in review UI",
    )
    timeout: int = Field(
        default=300,
        ge=5,
        le=3600,
        description="Timeout in seconds (default 5 min, max 1 hour, min 5s)",
    )
    require_comment_on_reject: bool = Field(
        default=True,
        description="Require comment when rejecting",
    )


class ActionConfig(BaseModel):
    """Configuration for a workflow action."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Unique action name")
    intent: str = Field(..., description="Clear description of action purpose")
    kind: ActionKind = Field(default=ActionKind.LLM, description="Type of action")
    impl: Optional[str] = Field(default=None, description="Implementation path for tool actions")
    model_vendor: Optional[str] = Field(
        default=None, description="Model vendor (openai, anthropic, etc.)"
    )
    model_name: Optional[str] = Field(default=None, description="Model name")
    output_schema: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None,
        description="Output schema",
        alias="schema",  # noqa: A003 — shadows builtin; rename breaks YAML compat
    )
    drops: List[str] = Field(
        default_factory=list, description="Fields to exclude from LLM prompt and final output"
    )
    observe: List[str] = Field(
        default_factory=list,
        description="Fields to pass-through from input to output without LLM "
        "generation (visible to LLM but not regenerated)",
    )
    granularity: Optional[Granularity] = Field(default=None, description="Execution granularity")
    guard: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None, description="Condition for action execution"
    )
    policy: Optional[str] = Field(default=None, description="Execution policy")
    versions: Optional[VersionConfig] = Field(default=None, description="Version configuration")
    version_consumption: Optional[VersionConsumptionConfig] = Field(
        default=None, description="Version output consumption configuration"
    )
    retry: Optional[RetryConfig] = Field(
        default=None, description="Retry configuration for transport-layer failures"
    )
    reprompt: Optional[RepromptConfig] = Field(
        default=None, description="Reprompt configuration for validation failures"
    )
    strict_schema: Optional[bool] = Field(
        default=None, description="Enable strict schema validation (reject on mismatch)"
    )
    on_schema_mismatch: Optional[Literal["warn", "reprompt", "reject"]] = Field(
        default=None, description="Schema mismatch mode: warn, reprompt, or reject"
    )
    idempotency_key: Optional[str] = Field(default=None, description="Idempotency key template")
    prompt: Optional[str] = Field(default=None, description="Prompt template or reference")
    dependencies: List[str] = Field(
        default_factory=list, description="List of upstream dependencies"
    )
    primary_dependency: Optional[str] = Field(
        default=None,
        description="Primary dependency for fan-in pattern (determines execution count)",
    )
    reduce_key: Optional[str] = Field(
        default=None,
        description="Key for aggregation pattern (groups merged outputs by this field)",
    )
    hitl: Optional[HitlConfig] = Field(
        default=None,
        description="HITL configuration (required when kind=hitl)",
    )
    on_empty: Literal["warn", "error", "skip"] = Field(
        default="warn",
        description="Behavior when action produces empty output: warn (log warning), "
        "error (fail workflow), skip (continue, emit event)",
    )

    # --- Fields from SIMPLE_CONFIG_FIELDS (not already above) ---
    api_key: Optional[str] = Field(default=None, description="API key")
    base_url: Optional[str] = Field(default=None, description="Base URL for vendors like Ollama")
    run_mode: Optional[str] = Field(default=None, description="Execution run mode")
    is_operational: Optional[bool] = Field(default=None, description="Whether action is enabled")
    json_mode: Optional[bool] = Field(default=None, description="JSON mode setting")
    prompt_debug: Optional[bool] = Field(default=None, description="Debug output for prompts")
    output_field: Optional[str] = Field(default=None, description="Output field name")
    temperature: Optional[float] = Field(default=None, description="Generation temperature")
    max_tokens: Optional[int] = Field(default=None, description="Maximum tokens")
    top_p: Optional[float] = Field(default=None, description="Top-p sampling parameter")
    stop: Optional[Union[str, List[str]]] = Field(default=None, description="Stop sequences")
    constraints: Optional[Any] = Field(default=None, description="Constraints for reprompting")

    # --- Runtime-consumed keys (from AgentConfig) ---
    where_clause: Optional[Dict[str, Any]] = Field(
        default=None, description="WHERE clause configuration for filtering"
    )
    ephemeral: Optional[bool] = Field(default=None, description="Ephemeral action outputs")
    anthropic_version: Optional[str] = Field(
        default=None, description="API version header for Anthropic requests"
    )
    enable_prompt_caching: Optional[bool] = Field(
        default=None, description="Enable Anthropic prompt caching"
    )
    max_execution_time: Optional[int] = Field(
        default=None, description="Maximum execution time in seconds"
    )
    enable_caching: Optional[bool] = Field(
        default=None, description="Enable caching for performance"
    )

    # --- Expander-consumed keys ---
    interceptors: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Interceptor configuration"
    )
    chunk_config: Optional[Dict[str, Any]] = Field(
        default=None, description="Chunking configuration"
    )
    chunk_size: Optional[int] = Field(default=None, description="Chunk size")
    chunk_overlap: Optional[int] = Field(default=None, description="Chunk overlap")
    context_scope: Optional[Dict[str, Any]] = Field(
        default=None, description="Context scope configuration"
    )
    version_mode: Optional[str] = Field(default=None, description="Version execution mode")
    child: Optional[List[str]] = Field(default=None, description="Child pipeline reference")

    # --- Internal (injected by render step) ---
    version_context: Optional[Dict[str, Any]] = Field(
        default=None, alias="_version_context", description="Version context injected by renderer"
    )

    @field_validator("retry", mode="before")
    @classmethod
    def validate_retry(cls, v):
        """Accept false (disable) but reject true (ambiguous — use mapping)."""
        if v is False or v is None:
            return None
        if v is True:
            raise ValueError("retry: true is not valid; use retry: {max_attempts: N} or omit")
        return v

    @field_validator("reprompt", mode="before")
    @classmethod
    def validate_reprompt(cls, v):
        """Accept false (disable) but reject true (ambiguous — use mapping)."""
        if v is False or v is None:
            return None
        if v is True:
            raise ValueError(
                "reprompt: true is not valid; use reprompt: {validation: fn_name} or omit"
            )
        return v

    @model_validator(mode="after")
    def validate_kind_requirements(self):
        """Ensure kind-specific fields are present."""
        if self.kind == ActionKind.HITL and self.hitl is None:
            raise ValueError("HITL actions require 'hitl' configuration block")
        if self.kind == ActionKind.TOOL and not self.impl:
            raise ValueError("Tool actions require 'impl' (implementation path)")
        return self

    @field_validator("guard")
    @classmethod
    def validate_guard(cls, v):
        """Validate guard expressions for safety."""
        if v:
            if isinstance(v, str):
                GuardParser.parse(v)
            elif isinstance(v, dict):
                parse_guard_config(v)
            else:
                raise ValueError(f"Guard must be string or dict, got {type(v)}")
        return v


class DefaultsConfig(BaseModel):
    """Default configuration applied to all actions."""

    # extra="ignore" (not "forbid"): workflow defaults may contain vendor-specific
    # params like frequency_penalty, presence_penalty that vary by provider and are
    # consumed by extract_generation_params(). Typed fields still validate known keys.
    model_config = ConfigDict(extra="ignore")

    model_vendor: Optional[str] = Field(default=None, description="Default model vendor")
    model_name: Optional[str] = Field(default=None, description="Default model name")
    json_mode: Optional[bool] = Field(default=None, description="Default JSON mode setting")
    granularity: Optional[Granularity] = Field(default=None, description="Default granularity")
    run_mode: Optional[str] = Field(default=None, description="Default run mode")
    drops: Optional[List[str]] = Field(
        default=None, description="Default fields to exclude from LLM prompt and output"
    )
    observe: Optional[List[str]] = Field(
        default=None,
        description="Default fields to pass-through from input to output "
        "(visible to LLM but not regenerated)",
    )
    data_source: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None,
        description="Default data source for start-node input",
    )
    hitl_timeout: Optional[int] = Field(
        default=None,
        ge=5,
        le=3600,
        description="Default HITL timeout in seconds for all hitl actions",
    )

    # --- Fields from SIMPLE_CONFIG_FIELDS (not already above) ---
    api_key: Optional[str] = Field(default=None, description="Default API key")
    base_url: Optional[str] = Field(default=None, description="Default base URL")
    kind: Optional[ActionKind] = Field(default=None, description="Default action kind")
    is_operational: Optional[bool] = Field(default=None, description="Default operational flag")
    prompt_debug: Optional[bool] = Field(default=None, description="Default prompt debug setting")
    output_field: Optional[str] = Field(default=None, description="Default output field name")
    temperature: Optional[float] = Field(default=None, description="Default temperature")
    max_tokens: Optional[int] = Field(default=None, description="Default max tokens")
    top_p: Optional[float] = Field(default=None, description="Default top-p")
    stop: Optional[Union[str, List[str]]] = Field(default=None, description="Default stop seq")
    reprompt: Optional[RepromptConfig] = Field(
        default=None, description="Default reprompt configuration"
    )
    constraints: Optional[Any] = Field(default=None, description="Default constraints")
    retry: Optional[RetryConfig] = Field(default=None, description="Default retry configuration")
    strict_schema: Optional[bool] = Field(default=None, description="Default strict schema flag")
    on_schema_mismatch: Optional[Literal["warn", "reprompt", "reject"]] = Field(
        default=None, description="Default schema mismatch mode"
    )

    # --- Expander-consumed keys ---
    context_scope: Optional[Dict[str, Any]] = Field(default=None, description="Default ctx scope")
    chunk_config: Optional[Dict[str, Any]] = Field(
        default=None, description="Default chunk configuration"
    )
    chunk_size: Optional[int] = Field(default=None, description="Default chunk size")
    chunk_overlap: Optional[int] = Field(default=None, description="Default chunk overlap")

    @field_validator("retry", mode="before")
    @classmethod
    def validate_retry(cls, v):
        """Accept false (disable) but reject true (ambiguous — use mapping)."""
        if v is False or v is None:
            return None
        if v is True:
            raise ValueError("retry: true is not valid; use retry: {max_attempts: N} or omit")
        return v

    @field_validator("reprompt", mode="before")
    @classmethod
    def validate_reprompt(cls, v):
        """Accept false (disable) but reject true (ambiguous — use mapping)."""
        if v is False or v is None:
            return None
        if v is True:
            raise ValueError(
                "reprompt: true is not valid; use reprompt: {validation: fn_name} or omit"
            )
        return v


class WorkflowConfigV2(BaseModel):
    """New workflow configuration format."""

    name: str = Field(..., description="Workflow name")
    description: str = Field(..., description="Workflow description")
    version: str = Field(..., description="Workflow version")
    defaults: Optional[DefaultsConfig] = Field(default=None, description="Default settings")
    actions: List[ActionConfig] = Field(..., description="Workflow actions")

    @model_validator(mode="after")
    def validate_workflow_invariants(self):
        """Check for duplicate action names and dangling dependency references."""
        names = [action.name for action in self.actions]
        seen = set()
        duplicates = set()
        for name in names:
            if name in seen:
                duplicates.add(name)
            seen.add(name)
        if duplicates:
            raise ValueError(f"Duplicate action names: {sorted(duplicates)}")

        all_deps = set()
        for action in self.actions:
            all_deps.update(action.dependencies)
        dangling = all_deps - seen
        if dangling:
            raise ValueError(
                f"Dangling dependency references (not defined as actions): {sorted(dangling)}"
            )

        # Iterative DFS cycle detection (avoids RecursionError on deep chains)
        dep_graph = self.get_dependency_graph()
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {name: WHITE for name in dep_graph}

        for start_node in dep_graph:
            if color[start_node] != WHITE:
                continue
            # stack entries: (node, iterator over its deps)
            stack = [(start_node, iter(dep_graph.get(start_node, [])))]
            color[start_node] = GRAY
            while stack:
                node, dep_iter = stack[-1]
                dep = next(dep_iter, None)
                if dep is None:
                    color[node] = BLACK
                    stack.pop()
                elif color[dep] == GRAY:
                    # Reconstruct cycle path from stack
                    cycle = [n for n, _ in stack]
                    idx = cycle.index(dep)
                    cycle = cycle[idx:]
                    cycle.append(dep)
                    raise ValueError(f"Circular dependency detected: {' -> '.join(cycle)}")
                elif color[dep] == WHITE:
                    color[dep] = GRAY
                    stack.append((dep, iter(dep_graph.get(dep, []))))

        return self

    def get_action(self, name: str) -> Optional[ActionConfig]:
        """Get an action by name."""
        return next((action for action in self.actions if action.name == name), None)

    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """Extract dependency graph from action definitions."""
        dependencies = {}
        for action in self.actions:
            dependencies[action.name] = action.dependencies
        return dependencies


__all__ = [
    "ActionKind",
    "Granularity",
    "HitlConfig",
    "VersionConfig",
    "RetryConfig",
    "RepromptConfig",
    "ActionConfig",
    "DefaultsConfig",
    "WorkflowConfigV2",
]
