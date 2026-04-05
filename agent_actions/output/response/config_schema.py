"""Configuration schema models for agent response processing."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from agent_actions.config.types import RunMode
from agent_actions.errors import ValidationError
from agent_actions.utils.constants import DANGEROUS_PATTERNS, contains_dangerous_pattern


class FilterScope(str, Enum):
    """Scope for WHERE clause filtering."""

    ITEM = "item"
    ACTION = "action"


class WhereClauseBehavior(str, Enum):
    """Behavior when WHERE clause condition fails."""

    SKIP = "skip"
    FILTER = "filter"


class WhereClauseConfig(BaseModel):
    """Configuration for WHERE clause filtering."""

    clause: str = Field(..., description="SQL-like WHERE clause for filtering", max_length=10000)
    scope: FilterScope = Field(
        default=FilterScope.ITEM,
        description=(
            "Filtering scope: 'item' for individual items, 'action' for entire action execution"
        ),
    )
    passthrough_on_empty: bool = Field(
        default=True, description="Pass data through if no matches found"
    )
    passthrough_on_error: bool = Field(
        default=True, description="Pass data through if evaluation error occurs"
    )
    cache_enabled: bool = Field(
        default=True, description="Enable caching of parsed WHERE clauses for performance"
    )
    behavior: WhereClauseBehavior = Field(
        default=WhereClauseBehavior.FILTER,
        description=("Behavior when condition fails: 'skip' (passthrough) or 'filter' (remove)"),
    )

    @field_validator("clause")
    @classmethod
    def validate_clause(cls, v):
        """Validate the WHERE clause syntax."""
        if v is not None and (not v or not v.strip()):
            raise ValidationError(
                "WHERE clause cannot be empty",
                context={
                    "clause": v,
                    "operation": "validate_where_clause",
                    "failed_field": "where_clause",
                    "expected": 'Non-empty WHERE clause (e.g., "column = value")',
                    "actual_value": v,
                    "suggestion": (
                        "Provide a valid WHERE clause with a condition, or remove "
                        "the where parameter if filtering is not needed."
                    ),
                },
            )
        if v is None:
            return v
        clause_lower = v.lower()
        matched = contains_dangerous_pattern(clause_lower, DANGEROUS_PATTERNS)
        if matched:
            raise ValidationError(
                f"WHERE clause contains potentially dangerous operation: {matched}",
                context={
                    "clause": v,
                    "dangerous_pattern": matched,
                    "operation": "validate_where_clause",
                    "failed_field": "where_clause",
                    "expected": (
                        "WHERE clause without dangerous patterns like exec, eval, __import__, etc."
                    ),
                    "actual_value": v,
                    "suggestion": (
                        f'Remove the dangerous pattern "{matched}" from your '
                        "WHERE clause. Use safe comparison operators and "
                        "column references only."
                    ),
                },
            )
        return v

    model_config = ConfigDict(extra="forbid")


class SkipConditionConfig(BaseModel):
    """Configuration for action skip conditions (safe replacement for eval-based skip_if)."""

    condition_type: Literal[
        "previous_outputs_empty", "previous_outputs_count", "field_condition", "custom"
    ] = Field(description="Type of skip condition")
    action_name: str | None = Field(
        default=None, description="Name of the action to check outputs for"
    )
    threshold: int | None = Field(default=None, description="Threshold for count-based conditions")
    comparison: Literal["==", "!=", "<", "<=", ">", ">="] | None = Field(
        default="==", description="Comparison operator for threshold"
    )
    field_path: str | None = Field(
        default=None, description="Path to field in previous outputs (dot notation)"
    )
    expected_value: Any | None = Field(
        default=None, description="Expected value for field condition"
    )
    expression: str | None = Field(
        default=None, description="Safe expression for custom conditions (no eval())"
    )

    @field_validator("expression")
    @classmethod
    def validate_expression(cls, v, info):
        """Validate custom expressions for safety."""
        if v and info.data.get("condition_type") == "custom":
            expr_lower = v.lower()
            matched = contains_dangerous_pattern(expr_lower, DANGEROUS_PATTERNS)
            if matched:
                raise ValidationError(
                    f"Expression contains potentially dangerous operation: {matched}",
                    context={
                        "expression": v,
                        "dangerous_pattern": matched,
                        "operation": "validate_skip_condition",
                        "failed_field": "expression",
                        "expected": (
                            "Safe custom expression without dangerous patterns "
                            "like exec, eval, __import__, etc."
                        ),
                        "actual_value": v,
                        "suggestion": (
                            f'Remove the dangerous pattern "{matched}" from your '
                            "skip condition expression. Use safe comparison "
                            "operators only."
                        ),
                    },
                )
        return v

    model_config = ConfigDict(extra="forbid")


class DefaultAgentConfig(BaseModel):
    """Default settings applied to each agent configuration (post-expansion stage).

    Used in ``ConfigManager.merge_agent_configs()`` to validate project-level
    defaults *after* ``ActionExpander`` has transformed actions into agents.
    For pre-expansion defaults validation, see ``DefaultsConfig`` in
    ``agent_actions.config.schema``.
    """

    api_key: SecretStr | None = None
    model_name: str | None = None
    chunk_config: dict[str, Any] | None = None
    is_operational: bool = True
    run_mode: RunMode = RunMode.ONLINE
    model_config = ConfigDict(extra="allow")


class AgentConfig(BaseModel):
    """Schema for an individual agent configuration entry (post-expansion stage).

    Validates the agent dict *after* ``ActionExpander`` has transformed
    pre-expansion ``ActionConfig`` dicts into the runtime agent shape
    (adding ``agent_type``, ``code_path``, ``schema_name``, etc.).

    Uses ``extra="allow"`` because the expander injects many fields
    not declared here.  For pre-expansion action validation, see
    ``ActionConfig`` in ``agent_actions.config.schema``.
    """

    agent_type: str
    name: str | None = None
    model_name: str | None = None
    model_vendor: str | None = Field(
        default=None,
        description=(
            "Model vendor/provider: 'openai', 'anthropic', 'gemini', 'groq', "
            "'mistral', 'cohere', 'ollama', 'tool', 'hitl', or 'agac-provider'"
        ),
    )
    api_key: SecretStr | None = None
    code_path: str | None = None
    dependencies: list[str | dict[str, Any]] = Field(default_factory=list)
    prompt: str | None = None
    schema_name: str | None = None
    chunk_config: dict[str, Any] = Field(default_factory=dict)
    observe: list[str] = Field(default_factory=list)
    drops: list[str] = Field(default_factory=list)
    is_operational: bool = True
    add_dispatch: bool | None = None
    run_mode: RunMode = RunMode.ONLINE
    json_mode: bool = Field(default=True, description="Enable JSON mode for structured output")
    prompt_debug: bool = Field(
        default=False, description="Enable debug output showing prompts being sent to the agent"
    )
    anthropic_version: str | None = Field(
        default=None, description="API version header for Anthropic requests (e.g., '2023-06-01')"
    )
    enable_prompt_caching: bool | None = Field(
        default=None,
        description="Enable Anthropic's prompt caching feature for improved performance",
    )
    conditional_clause: str | None = Field(
        default=None, description="Legacy conditional clause (deprecated, use where_clause instead)"
    )
    skip_if: str | None = Field(
        default=None, description="Legacy skip condition (deprecated, use skip_condition instead)"
    )
    where_clause: WhereClauseConfig | None = Field(
        default=None, description="WHERE clause configuration for advanced filtering"
    )
    skip_condition: SkipConditionConfig | None = Field(
        default=None, description="Safe skip condition configuration"
    )
    max_execution_time: int | None = Field(
        default=300, description="Maximum execution time in seconds"
    )
    enable_caching: bool = Field(default=True, description="Enable caching for performance")
    context_scope: dict[str, Any] | None = Field(
        default=None,
        description="Context scope configuration for data visibility and flow control "
        "(seed_path, observe, drop directives). Normalized in-place by config pipeline "
        "(version references expanded to field prefix patterns).",
    )

    model_config = ConfigDict(extra="allow")


__all__ = [
    "DefaultAgentConfig",
    "AgentConfig",
    "WhereClauseConfig",
    "FilterScope",
    "SkipConditionConfig",
]
