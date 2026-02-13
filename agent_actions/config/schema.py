"""Schema definitions for the new workflow format."""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from agent_actions.errors import ConfigValidationError
from agent_actions.output.response.guard_parser import GuardParser
from agent_actions.output.response.consolidated_guard import parse_guard_config


class ActionKind(str, Enum):
    """Types of actions in the workflow."""

    LLM = "llm"
    TOOL = "tool"
    HITL = "hitl"


class Granularity(str, Enum):
    """Granularity levels for action execution."""

    RECORD = "record"
    FILE = "file"


class VersionMode(str, Enum):
    """Version execution modes."""

    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class VersionConfig(BaseModel):
    """Configuration for version-based actions."""

    param: str = Field(..., description="Parameter name for version variable")
    range: List[int] = Field(..., description="Range of values for version parameter")
    mode: VersionMode = Field(default=VersionMode.PARALLEL, description="Execution mode")


class MergePattern(str, Enum):
    """Patterns for merging version outputs."""

    MERGE = "merge"


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
    """Configuration for reprompt behavior on validation failures."""

    validation: str = Field(..., description="Name of validation UDF function")
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

    name: str = Field(..., description="Unique action name")
    intent: str = Field(..., description="Clear description of action purpose")
    kind: ActionKind = Field(default=ActionKind.LLM, description="Type of action")
    impl: Optional[str] = Field(default=None, description="Implementation path for tool actions")
    model_vendor: Optional[str] = Field(
        default=None, description="Model vendor (openai, anthropic, etc.)"
    )
    model_name: Optional[str] = Field(default=None, description="Model name")
    output_schema: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None, description="Output schema", alias="schema"
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

    @model_validator(mode="after")
    def validate_hitl_config(self):
        """Ensure HITL config is present when kind=hitl."""
        if self.kind == ActionKind.HITL and self.hitl is None:
            raise ValueError("HITL actions require 'hitl' configuration block")
        return self

    @field_validator("guard")
    @classmethod
    def validate_guard(cls, v):
        """Validate guard expressions for safety."""
        if v:
            try:
                if isinstance(v, str):
                    GuardParser.parse(v)
                elif isinstance(v, dict):
                    parse_guard_config(v)
                else:
                    raise ConfigValidationError(
                        "guard_type",
                        f"Guard must be string or dict, got {type(v)}",
                        context={"guard_type": str(type(v)), "operation": "validate_guard"},
                    )
            except ValueError as e:
                raise ConfigValidationError(
                    "guard_expression",
                    f"Invalid guard: {e}",
                    context={"guard": v, "operation": "validate_guard"},
                    cause=e,
                ) from e
        return v


class DefaultsConfig(BaseModel):
    """Default configuration applied to all actions."""

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


class WorkflowConfigV2(BaseModel):
    """New workflow configuration format."""

    name: str = Field(..., description="Workflow name")
    description: str = Field(..., description="Workflow description")
    version: str = Field(..., description="Workflow version")
    defaults: Optional[DefaultsConfig] = Field(default=None, description="Default settings")
    actions: List[ActionConfig] = Field(..., description="Workflow actions")

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
    "ActionConfig",
    "DefaultsConfig",
    "WorkflowConfigV2",
]
