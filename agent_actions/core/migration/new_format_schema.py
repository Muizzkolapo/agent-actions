"""Schema definitions for the new workflow format."""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any, Literal, Union
from enum import Enum


class ActionKind(str, Enum):
    """Types of actions in the workflow."""
    LLM = "llm"  # Default - Language model agent
    TOOL = "tool"  # Tool/function execution


class Granularity(str, Enum):
    """Granularity levels for action execution."""
    RECORD = "record"
    FILE = "file"


class LoopConfig(BaseModel):
    """Configuration for loop-based actions."""
    param: str = Field(..., description="Parameter name for loop variable")
    range: List[int] = Field(..., description="Range of values for loop parameter")


class MergePattern(str, Enum):
    """Patterns for merging loop outputs."""
    MERGE = "merge"  # Dict.update() behavior (last wins)


class LoopConsumptionConfig(BaseModel):
    """Configuration for consuming loop outputs."""
    source: str = Field(..., description="Base name of the loop action to consume")
    pattern: MergePattern = Field(default=MergePattern.MERGE, description="Pattern for merging loop outputs")


class ActionConfig(BaseModel):
    """Configuration for a workflow action."""

    name: str = Field(..., description="Unique action name")
    intent: str = Field(..., description="Clear description of action purpose")
    kind: ActionKind = Field(default=ActionKind.LLM, description="Type of action")

    # Implementation details
    impl: Optional[str] = Field(default=None, description="Implementation path for tool actions")
    vendor: Optional[str] = Field(default=None, description="Model vendor (openai, anthropic, etc.)")
    model: Optional[str] = Field(default=None, description="Model name")

    # Schema and data handling
    output_schema: Optional[Union[str, Dict[str, Any]]] = Field(default=None, description="Output schema", alias="schema")
    reads: List[str] = Field(default_factory=list, description="Fields to read from input")
    writes: List[str] = Field(default_factory=list, description="Fields to write to output")
    drops: List[str] = Field(default_factory=list, description="Fields to drop from output")
    observe: List[str] = Field(default_factory=list, description="Fields to observe but not consume")

    # Execution settings
    granularity: Optional[Granularity] = Field(default=None, description="Execution granularity")
    guard: Optional[Union[str, Dict[str, Any]]] = Field(default=None, description="Condition for action execution")
    policy: Optional[str] = Field(default=None, description="Execution policy")
    few_shot: Optional[int] = Field(default=None, description="Number of few-shot examples")

    # Advanced features
    loop: Optional[LoopConfig] = Field(default=None, description="Loop configuration")
    loop_consumption: Optional[LoopConsumptionConfig] = Field(default=None, description="Loop output consumption configuration")
    idempotency_key: Optional[str] = Field(default=None, description="Idempotency key template")

    # Prompt and execution
    prompt: Optional[str] = Field(default=None, description="Prompt template or reference")

    @field_validator('guard')
    @classmethod
    def validate_guard(cls, v):
        """Validate guard expressions for safety."""
        if v:
            try:
                if isinstance(v, str):
                    # Legacy string format
                    from agent_actions.core.utils.guard_parser import GuardParser
                    GuardParser.parse(v)
                elif isinstance(v, dict):
                    # New consolidated format
                    from agent_actions.core.utils.consolidated_guard import parse_guard_config
                    parse_guard_config(v)
                else:
                    raise ValueError(f"Guard must be string or dict, got {type(v)}")
            except ValueError as e:
                raise ValueError(f"Invalid guard: {e}")
        return v


class DefaultsConfig(BaseModel):
    """Default configuration applied to all actions."""

    vendor: Optional[str] = Field(default=None, description="Default model vendor")
    model: Optional[str] = Field(default=None, description="Default model name")
    json_mode: Optional[bool] = Field(default=None, description="Default JSON mode setting")
    granularity: Optional[Granularity] = Field(default=None, description="Default granularity")
    run_mode: Optional[str] = Field(default=None, description="Default run mode")


class DependencyEdge(BaseModel):
    """Represents a dependency relationship in the execution plan."""

    action: str = Field(..., description="Action name")
    depends_on: List[str] = Field(default_factory=list, description="Actions this depends on")


class WorkflowConfigV2(BaseModel):
    """New workflow configuration format."""

    name: str = Field(..., description="Workflow name")
    description: str = Field(..., description="Workflow description")
    version: str = Field(..., description="Workflow version")

    defaults: Optional[DefaultsConfig] = Field(default=None, description="Default settings")
    actions: List[ActionConfig] = Field(..., description="Workflow actions")
    plan: List[str] = Field(..., description="Execution plan with dependencies")

    @field_validator('plan')
    @classmethod
    def validate_plan(cls, v, info):
        """Validate that all actions in plan are defined."""
        if 'actions' in info.data:
            action_names = {action.name for action in info.data['actions']}

            for plan_item in v:
                # Handle dependency syntax: "action_name <- dep1, dep2"
                if '<-' in plan_item:
                    action_name = plan_item.split('<-')[0].strip()
                else:
                    action_name = plan_item.strip()

                if action_name not in action_names:
                    raise ValueError(f"Action '{action_name}' in plan not defined in actions")
        return v

    def get_action(self, name: str) -> Optional[ActionConfig]:
        """Get an action by name."""
        return next((action for action in self.actions if action.name == name), None)

    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """Extract dependency graph from execution plan."""
        dependencies = {}

        for plan_item in self.plan:
            if '<-' in plan_item:
                parts = plan_item.split('<-')
                action_name = parts[0].strip()
                deps = [dep.strip() for dep in parts[1].split(',')]
                dependencies[action_name] = deps
            else:
                action_name = plan_item.strip()
                dependencies[action_name] = []

        return dependencies


__all__ = [
    "ActionKind",
    "Granularity",
    "LoopConfig",
    "ActionConfig",
    "DefaultsConfig",
    "DependencyEdge",
    "WorkflowConfigV2"
]