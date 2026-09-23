"""Schema definitions for the new workflow format."""

import difflib
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from agent_actions.config.types import Granularity, RunMode
from agent_actions.guards import GuardParser, parse_guard_config

# Measured: a transposition or a dropped letter scores 0.667 and above, a
# spelling belonging to no field 0.600 and below. Distinct names still collide,
# so a suggestion is a guess offered beside the full list, not a diagnosis.
_NEAR_MISS_CUTOFF = 0.65
_SQLITE_MAX_INT = 2**63 - 1


def _refuse_undeclared_keys(data: Any, model: type[BaseModel], surface: str) -> Any:
    """Name every undeclared key, what each resembles, and the keys *surface* takes.

    The list is unconditional: a guess is a string-distance match, so it lands on
    a real field often enough that a reader given only the guess is left with
    nothing when it is wrong.
    """
    if not isinstance(data, dict):
        return data
    accepted = sorted(model.model_fields)
    stray = sorted(str(key) for key in data if str(key) not in accepted)
    if not stray:
        return data

    problems = []
    for key in stray:
        near = difflib.get_close_matches(key, accepted, n=1, cutoff=_NEAR_MISS_CUTOFF)
        problems.append(
            f"unknown {surface} key '{key}' — did you mean '{near[0]}'?"
            if near
            else f"unknown {surface} key '{key}'"
        )
    problems.append(f"valid {surface} keys are " + ", ".join(accepted))
    raise ValueError("; ".join(problems))


def _validate_bool_or_mapping(v: Any, field_name: str, usage_hint: str) -> Any:
    if v is False or v is None:
        return None
    if v is True:
        raise ValueError(f"{field_name}: true is not valid; {usage_hint}")
    return v


class ActionKind(str, Enum):
    """Types of actions in the workflow."""

    LLM = "llm"
    TOOL = "tool"
    HITL = "hitl"
    SOURCE = "source"  # Special: workflow input data
    SEED = "seed"  # Special: static seed data

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

    model_config = ConfigDict(extra="forbid")

    param: str = Field(default="i", description="Parameter name for version variable")
    range: list[int] = Field(  # noqa: A003 — shadows builtin; rename breaks YAML compat
        ..., description="Range of values for version parameter"
    )
    mode: VersionMode = Field(default=VersionMode.PARALLEL, description="Execution mode")


class MergePattern(str, Enum):
    """Patterns for version output consumption."""

    MERGE = "merge"
    MATCH = "match"


class VersionConsumptionConfig(BaseModel):
    """Configuration for consuming version outputs."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., description="Base name of the version action to consume")
    pattern: MergePattern = Field(
        default=MergePattern.MERGE, description="Pattern for merging version outputs"
    )


class RetryConfig(BaseModel):
    """Configuration for retry behavior on transport-layer failures."""

    model_config = ConfigDict(extra="forbid")

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


class HitlConfig(BaseModel):
    """Configuration for Human-in-the-Loop actions."""

    model_config = ConfigDict(extra="forbid")

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
    rejection_reasons: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Optional list of rejection reason labels shown in the review UI",
    )

    @field_validator("rejection_reasons")
    @classmethod
    def _validate_rejection_reasons(cls, v: list[str]) -> list[str]:
        return [r.strip() for r in v if r and r.strip()]


class _RetryValidators(BaseModel):
    """Shared before-mode coercion for the retry shorthand field."""

    @field_validator("retry", mode="before", check_fields=False)
    @classmethod
    def validate_retry(cls, v):
        return _validate_bool_or_mapping(v, "retry", "use retry: {max_attempts: N} or omit")


class ExpectConfig(BaseModel):
    """Binds an expectation suite to an action, with its enforcement policy."""

    model_config = ConfigDict(extra="forbid")

    suite: str | None = Field(
        default=None,
        description="Schema-path file whose rules — on its fields, in its own expectations: block, or both — supply this action's; "
        "omitted with no inline list, the action's own schema: file is read",
    )
    expectations: list[dict[str, Any]] | None = Field(
        default=None, description="Inline expectation list, in place of a named suite"
    )
    max_iterations: int = Field(
        default=3, ge=1, le=10, description="Maximum generate-validate-repair iterations (1-10)"
    )
    repair: str | dict[str, Any] = Field(
        default="auto",
        description="none (observe), retry (re-run prompt), or auto (composed feedback); "
        "the {prompt: $wf.X} mapping form is reserved and not implemented yet",
    )
    structural: str | dict[str, Any] = Field(
        default="retry",
        description="How a schema failure is regenerated: retry (re-send the original prompt), "
        "auto (send the schema feedback), or {prompt: $wf.X}; repair: governs rule failures",
    )
    on_exhausted: Literal["return_last", "fail", "raise"] = Field(
        default="return_last",
        description="Behavior when iterations exhaust: return_last, fail (tombstone), or raise",
    )
    judge_budget: int | None = Field(
        default=None,
        ge=1,
        description="Max real judge LLM calls this action's suite may make across the run; "
        "None is uncapped",
    )

    @field_validator("repair", "structural")
    @classmethod
    def validate_repair(cls, v):
        if isinstance(v, str):
            if v not in ("none", "retry", "auto"):
                raise ValueError(f"repair must be one of: none, retry, auto. Got: {v!r}")
            return v
        if isinstance(v, dict):
            if set(v) != {"prompt"}:
                raise ValueError(
                    f"repair mapping takes exactly one key, 'prompt'. Got: {sorted(v)}"
                )
            return v
        raise ValueError(f"repair must be a string or a mapping, got {type(v).__name__}")

    @model_validator(mode="after")
    def validate_suite_source(self):
        if self.suite is not None and self.expectations is not None:
            raise ValueError(
                "expect takes at most one of:\n"
                "  suite: my_rules        # a schema-path file with an expectations: block\n"
                "  expectations: [...]    # an inline list\n"
                "Omit both to read the rules of the action's own schema."
            )
        if self.suite == "":
            raise ValueError(
                "suite: must not be empty; name a schema-path file, or omit the "
                "key to read the action's own schema"
            )
        if self.expectations == []:
            raise ValueError(
                "expectations: must not be an empty list; add entries, or omit "
                "the key to read the action's own schema"
            )
        return self

    @model_validator(mode="after")
    def validate_observe_mode_has_no_loop_keys(self):
        if self.repair == "none":
            offenders = sorted({"max_iterations", "on_exhausted"} & self.model_fields_set)
            if offenders:
                raise ValueError(
                    f"repair: none never loops, so {offenders} have no meaning. "
                    "Remove them, or choose repair: retry or repair: auto."
                )
        return self


class ActionConfig(_RetryValidators):
    """Configuration for a workflow action."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Unique action name")
    intent: str = Field(..., description="Clear description of action purpose")
    kind: ActionKind = Field(default=ActionKind.LLM, description="Type of action")
    impl: str | None = Field(default=None, description="Implementation path for tool actions")
    model_vendor: str | None = Field(
        default=None, description="Model vendor (openai, anthropic, etc.)"
    )
    model_name: str | None = Field(default=None, description="Model name")
    output_schema: str | dict[str, Any] | None = Field(
        default=None,
        description="Output schema",
        alias="schema",  # noqa: A003 — shadows builtin; rename breaks YAML compat
    )
    drops: list[str] = Field(
        default_factory=list, description="Fields to exclude from LLM prompt and final output"
    )
    observe: list[str] = Field(
        default_factory=list,
        description="Fields to pass-through from input to output without LLM "
        "generation (visible to LLM but not regenerated)",
    )
    granularity: Granularity | None = Field(default=None, description="Execution granularity")
    guard: str | dict[str, Any] | None = Field(
        default=None, description="Condition for action execution"
    )
    policy: str | None = Field(default=None, description="Execution policy")
    versions: VersionConfig | None = Field(default=None, description="Version configuration")
    version_consumption: VersionConsumptionConfig | None = Field(
        default=None, description="Version output consumption configuration"
    )
    expect: ExpectConfig | None = Field(
        default=None, description="Output expectations and their enforcement policy"
    )
    retry: RetryConfig | None = Field(
        default=None, description="Retry configuration for transport-layer failures"
    )
    idempotency_key: str | None = Field(default=None, description="Idempotency key template")
    prompt: str | None = Field(default=None, description="Prompt template or reference")
    dependencies: list[str] = Field(
        default_factory=list, description="List of upstream dependencies"
    )
    primary_dependency: str | None = Field(
        default=None,
        description="Primary dependency for fan-in pattern (determines execution count)",
    )
    reduce_key: str | None = Field(
        default=None,
        description="Key for aggregation pattern (groups merged outputs by this field)",
    )
    hitl: HitlConfig | None = Field(
        default=None,
        description="HITL configuration (required when kind=hitl)",
    )
    on_empty: Literal["warn", "error", "skip"] = Field(
        default="warn",
        description="Behavior when action produces empty output: warn (log warning), "
        "error (fail workflow), skip (continue, emit event)",
    )
    defaults: dict[str, Any] | None = Field(
        default=None,
        description="Per-output-field default values a tool UDF is expected to "
        "synthesize when upstream input omits the field. Consumed by the DAG "
        "schema-fit preflight check to exclude declared fields from the "
        "implicit-input requirement set. The framework does not apply these "
        "defaults automatically — the UDF must produce them.",
    )

    # --- Fields from SIMPLE_CONFIG_FIELDS (not already above) ---
    api_key: SecretStr | None = Field(default=None, description="API key")
    base_url: str | None = Field(default=None, description="Base URL for vendors like Ollama")
    run_mode: RunMode | None = Field(default=None, description="Execution run mode")
    is_operational: bool | None = Field(default=None, description="Whether action is enabled")
    json_mode: bool | None = Field(default=None, description="JSON mode setting")
    prompt_debug: bool | None = Field(default=None, description="Debug output for prompts")
    output_field: str | None = Field(default=None, description="Output field name")
    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Generation temperature"
    )
    max_tokens: int | None = Field(default=None, description="Maximum tokens")
    top_p: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Top-p sampling parameter"
    )
    frequency_penalty: float | None = Field(
        default=None, ge=-2.0, le=2.0, description="Frequency penalty (OpenAI, Groq)"
    )
    presence_penalty: float | None = Field(
        default=None, ge=-2.0, le=2.0, description="Presence penalty (OpenAI, Groq)"
    )
    stop: str | list[str] | None = Field(default=None, description="Stop sequences")
    constraints: Any | None = Field(default=None, description="Generation constraints")

    # --- Runtime-consumed keys (from AgentConfig) ---
    where_clause: dict[str, Any] | None = Field(
        default=None, description="WHERE clause configuration for filtering"
    )
    anthropic_version: str | None = Field(
        default=None, description="API version header for Anthropic requests"
    )
    enable_prompt_caching: bool | None = Field(
        default=None, description="Enable Anthropic prompt caching"
    )
    max_execution_time: int | None = Field(
        default=None, description="Maximum execution time in seconds"
    )
    enable_caching: bool | None = Field(default=None, description="Enable caching for performance")

    # --- Limit controls ---
    record_limit: int | None = Field(
        default=None, ge=1, description="Max records per file, at any action"
    )
    file_limit: int | None = Field(default=None, ge=1, description="Max files to walk per action")

    # --- Batch concurrency (Ollama only) ---
    batch_max_workers: int | None = Field(
        default=None, ge=1, le=32, description="Max concurrent workers for Ollama batch processing"
    )

    # --- Expander-consumed keys ---
    interceptors: list[dict[str, Any]] | None = Field(
        default=None, description="Interceptor configuration"
    )
    chunk_config: dict[str, Any] | None = Field(default=None, description="Chunking configuration")
    chunk_size: int | None = Field(default=None, description="Chunk size")
    chunk_overlap: int | None = Field(default=None, description="Chunk overlap")
    context_scope: dict[str, Any] | None = Field(
        default=None, description="Context scope configuration"
    )
    version_mode: VersionMode | None = Field(default=None, description="Version execution mode")

    # --- Internal (injected by render step) ---
    version_context: dict[str, Any] | None = Field(
        default=None, alias="_version_context", description="Version context injected by renderer"
    )

    @model_validator(mode="after")
    def validate_kind_requirements(self):
        """Ensure kind-specific fields are present."""
        if self.kind == ActionKind.HITL and self.hitl is None:
            raise ValueError(f"HITL action '{self.name}' requires 'hitl' configuration block")
        if self.kind == ActionKind.TOOL and not self.impl:
            raise ValueError(f"Tool action '{self.name}' requires 'impl' (implementation path)")
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


class DefaultsConfig(_RetryValidators):
    """Default configuration applied to all actions."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _no_undeclared_keys(cls, data: Any) -> Any:
        return _refuse_undeclared_keys(data, cls, "defaults")

    model_vendor: str | None = Field(default=None, description="Default model vendor")
    model_name: str | None = Field(default=None, description="Default model name")
    json_mode: bool | None = Field(default=None, description="Default JSON mode setting")
    granularity: Granularity | None = Field(default=None, description="Default granularity")
    run_mode: RunMode | None = Field(default=None, description="Default run mode")
    drops: list[str] | None = Field(
        default=None, description="Default fields to exclude from LLM prompt and output"
    )
    observe: list[str] | None = Field(
        default=None,
        description="Default fields to pass-through from input to output "
        "(visible to LLM but not regenerated)",
    )
    data_source: str | dict[str, Any] | None = Field(
        default=None,
        description="Default data source for start-node input",
    )
    hitl_timeout: int | None = Field(
        default=None,
        ge=5,
        le=3600,
        description="Default HITL timeout in seconds for all hitl actions",
    )

    # --- Fields from SIMPLE_CONFIG_FIELDS (not already above) ---
    api_key: SecretStr | None = Field(default=None, description="Default API key")
    base_url: str | None = Field(default=None, description="Default base URL")
    kind: ActionKind | None = Field(default=None, description="Default action kind")
    is_operational: bool | None = Field(default=None, description="Default operational flag")
    prompt_debug: bool | None = Field(default=None, description="Default prompt debug setting")
    output_field: str | None = Field(default=None, description="Default output field name")
    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Default temperature"
    )
    max_tokens: int | None = Field(default=None, description="Default max tokens")
    top_p: float | None = Field(default=None, ge=0.0, le=1.0, description="Default top-p")
    frequency_penalty: float | None = Field(
        default=None, ge=-2.0, le=2.0, description="Default frequency penalty (OpenAI, Groq)"
    )
    presence_penalty: float | None = Field(
        default=None, ge=-2.0, le=2.0, description="Default presence penalty (OpenAI, Groq)"
    )
    stop: str | list[str] | None = Field(default=None, description="Default stop seq")
    constraints: Any | None = Field(default=None, description="Default constraints")
    retry: RetryConfig | None = Field(default=None, description="Default retry configuration")
    expect: ExpectConfig | None = Field(
        default=None,
        description="Default output expectations and enforcement policy; an action's own "
        "expect: block merges over this key by key",
    )

    # --- Expander-consumed keys ---
    context_scope: dict[str, Any] | None = Field(default=None, description="Default ctx scope")
    chunk_config: dict[str, Any] | None = Field(
        default=None, description="Default chunk configuration"
    )
    chunk_size: int | None = Field(default=None, description="Default chunk size")
    chunk_overlap: int | None = Field(default=None, description="Default chunk overlap")

    # --- Read out of defaults by field inheritance ---
    where_clause: dict[str, Any] | None = Field(
        default=None, description="Default WHERE clause configuration for filtering"
    )
    anthropic_version: str | None = Field(
        default=None, description="Default API version header for Anthropic requests"
    )
    enable_prompt_caching: bool | None = Field(
        default=None, description="Default Anthropic prompt caching setting"
    )
    max_execution_time: int | None = Field(
        default=None, description="Default maximum execution time in seconds"
    )
    enable_caching: bool | None = Field(default=None, description="Default caching setting")
    tokenizer_model: str | None = Field(default=None, description="Default tokenizer model")
    split_method: str | None = Field(default=None, description="Default chunk split method")

    # --- Limit controls ---
    record_limit: int | None = Field(default=None, ge=1, description="Default record limit")
    file_limit: int | None = Field(default=None, ge=1, description="Default file limit")

    # --- Batch concurrency (Ollama only) ---
    batch_max_workers: int | None = Field(
        default=None,
        ge=1,
        le=32,
        description="Default max concurrent workers for Ollama batch processing",
    )


class StorageConfig(BaseModel):
    """Storage maintenance knobs, read off the workflow's own top-level `storage:`."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _no_undeclared_keys(cls, data: Any) -> Any:
        data = _refuse_undeclared_keys(data, cls, "storage")
        if isinstance(data, dict):
            blank = sorted(str(key) for key, value in data.items() if value is None)
            if blank:
                # An empty key beats the default, because the consumer reads the
                # raw dict; for retention that None then reaches a `< 1`.
                raise ValueError(
                    "; ".join(
                        f"storage key '{key}' is present with no value — omit it to take "
                        f"the default, or give it a number"
                        for key in blank
                    )
                )
        return data

    # ge=0 because both enforcers open `if <value> < 1: return`; strict because the
    # consumer reads the raw dict, so a coerced "10" reaches it as the string; the
    # ceiling is SQLite's, past which OFFSET raises an OverflowError nothing catches.
    prompt_trace_retention_runs: int | None = Field(
        default=None,
        ge=0,
        le=_SQLITE_MAX_INT,
        strict=True,
        description="Calendar days of prompt traces to keep; 0 never prunes",
    )
    source_data_ttl_days: int | None = Field(
        default=None,
        ge=0,
        le=_SQLITE_MAX_INT,
        strict=True,
        description="Days of source data to keep; 0 never prunes",
    )


class WorkflowConfig(BaseModel):
    """Pydantic schema for user-facing workflow YAML files.

    Validates the complete workflow structure including all actions,
    defaults, and cross-cutting invariants (duplicate names, dangling
    dependencies, circular dependencies).
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _no_undeclared_keys(cls, data: Any) -> Any:
        data = _refuse_undeclared_keys(data, cls, "workflow")
        if isinstance(data, dict) and "storage" in data and data["storage"] is None:
            # `storage:` left empty is None, not {}, and the consumer reads the raw
            # dict — `get("storage", {})` returns that None and then `.get` on it.
            raise ValueError(
                "workflow key 'storage' is present with no value — remove the block, "
                "or give it a setting"
            )
        return data

    name: str = Field(..., description="Workflow name")
    description: str = Field(..., description="Workflow description")
    version: str | None = Field(default=None, description="Workflow version")
    defaults: DefaultsConfig | None = Field(default=None, description="Default settings")
    actions: list[ActionConfig] = Field(..., description="Workflow actions")
    tool_path: str | list[str] | None = Field(
        default=None,
        description="Where this workflow's UDFs live, ahead of the default and project config",
    )
    storage: StorageConfig | None = Field(
        default=None, description="Storage maintenance settings for this workflow"
    )

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

        # Version base names (e.g. "score_quality") are valid dependency targets
        # even though only their expanded variants exist as concrete actions.
        base_names: set[str] = set()
        all_deps: set[str] = set()
        for action in self.actions:
            all_deps.update(action.dependencies)
            if action.version_context and "base_name" in action.version_context:
                base_names.add(action.version_context["base_name"])
        dangling = all_deps - seen - base_names
        if dangling:
            raise ValueError(
                f"Dangling dependency references (not defined as actions): {sorted(dangling)}"
            )

        # Validate primary_dependency references exist as action names
        invalid_primary = [
            (action.name, action.primary_dependency)
            for action in self.actions
            if action.primary_dependency is not None and action.primary_dependency not in seen
        ]
        if invalid_primary:
            details = ", ".join(f"'{a}' references '{p}'" for a, p in invalid_primary)
            raise ValueError(f"primary_dependency references non-existent action(s): {details}")

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
                elif dep not in color:
                    # Versioned base name (e.g. "score_quality") — already
                    # validated by the dangling-dep check above; skip in DFS.
                    continue
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

    def get_action(self, name: str) -> ActionConfig | None:
        """Get an action by name."""
        return next((action for action in self.actions if action.name == name), None)

    def get_dependency_graph(self) -> dict[str, list[str]]:
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
    "ActionConfig",
    "StorageConfig",
    "DefaultsConfig",
    "WorkflowConfig",
]
