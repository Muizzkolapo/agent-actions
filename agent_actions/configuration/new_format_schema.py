"""Schema definitions for the new workflow format."""
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any, Union
from enum import Enum

class ActionKind(str, Enum):
    """Types of actions in the workflow."""
    LLM = 'llm'
    TOOL = 'tool'

class Granularity(str, Enum):
    """Granularity levels for action execution."""
    RECORD = 'record'
    FILE = 'file'

class LoopMode(str, Enum):
    """Loop execution modes."""
    PARALLEL = 'parallel'
    SEQUENTIAL = 'sequential'

class LoopConfig(BaseModel):
    """Configuration for loop-based actions."""
    param: str = Field(..., description='Parameter name for loop variable')
    range: List[int] = Field(..., description='Range of values for loop parameter')
    mode: LoopMode = Field(default=LoopMode.PARALLEL, description='Execution mode')

class MergePattern(str, Enum):
    """Patterns for merging loop outputs."""
    MERGE = 'merge'

class LoopConsumptionConfig(BaseModel):
    """Configuration for consuming loop outputs."""
    source: str = Field(..., description='Base name of the loop action to consume')
    pattern: MergePattern = Field(default=MergePattern.MERGE, description='Pattern for merging loop outputs')

class ActionConfig(BaseModel):
    """Configuration for a workflow action."""
    name: str = Field(..., description='Unique action name')
    intent: str = Field(..., description='Clear description of action purpose')
    kind: ActionKind = Field(default=ActionKind.LLM, description='Type of action')
    impl: Optional[str] = Field(default=None, description='Implementation path for tool actions')
    model_vendor: Optional[str] = Field(default=None, description='Model vendor (openai, anthropic, etc.)')
    model_name: Optional[str] = Field(default=None, description='Model name')
    output_schema: Optional[Union[str, Dict[str, Any]]] = Field(default=None, description='Output schema', alias='schema')
    drops: List[str] = Field(default_factory=list, description='Fields to exclude from LLM prompt and final output')
    observe: List[str] = Field(default_factory=list, description='Fields to pass-through from input to output without LLM generation (visible to LLM but not regenerated)')
    granularity: Optional[Granularity] = Field(default=None, description='Execution granularity')
    guard: Optional[Union[str, Dict[str, Any]]] = Field(default=None, description='Condition for action execution')
    policy: Optional[str] = Field(default=None, description='Execution policy')
    few_shot: Optional[int] = Field(default=None, description='Number of few-shot examples')
    loop: Optional[LoopConfig] = Field(default=None, description='Loop configuration')
    loop_consumption: Optional[LoopConsumptionConfig] = Field(default=None, description='Loop output consumption configuration')
    idempotency_key: Optional[str] = Field(default=None, description='Idempotency key template')
    prompt: Optional[str] = Field(default=None, description='Prompt template or reference')

    @field_validator('guard')
    @classmethod
    def validate_guard(cls, v):
        """Validate guard expressions for safety."""
        if v:
            try:
                if isinstance(v, str):
                    from agent_actions.response_processing.guard_parser import GuardParser
                    GuardParser.parse(v)
                elif isinstance(v, dict):
                    from agent_actions.utilities.consolidated_guard import parse_guard_config
                    parse_guard_config(v)
                else:
                    from agent_actions.shared.exceptions import ConfigValidationError as CVE
                    raise CVE('guard_type', f'Guard must be string or dict, got {type(v)}', context={'guard_type': str(type(v)), 'operation': 'validate_guard'})
            except ValueError as e:
                from agent_actions.shared.exceptions import ConfigValidationError as CVE
                raise CVE('guard_expression', f'Invalid guard: {e}', context={'guard': v, 'operation': 'validate_guard'}, cause=e)
        return v


class DefaultsConfig(BaseModel):
    """Default configuration applied to all actions."""
    model_vendor: Optional[str] = Field(default=None, description='Default model vendor')
    model_name: Optional[str] = Field(default=None, description='Default model name')
    json_mode: Optional[bool] = Field(default=None, description='Default JSON mode setting')
    granularity: Optional[Granularity] = Field(default=None, description='Default granularity')
    run_mode: Optional[str] = Field(default=None, description='Default run mode')
    drops: Optional[List[str]] = Field(default=None, description='Default fields to exclude from LLM prompt and output')
    observe: Optional[List[str]] = Field(default=None, description='Default fields to pass-through from input to output (visible to LLM but not regenerated)')

class DependencyEdge(BaseModel):
    """Represents a dependency relationship in the execution plan."""
    action: str = Field(..., description='Action name')
    depends_on: List[str] = Field(default_factory=list, description='Actions this depends on')

class WorkflowConfigV2(BaseModel):
    """New workflow configuration format."""
    name: str = Field(..., description='Workflow name')
    description: str = Field(..., description='Workflow description')
    version: str = Field(..., description='Workflow version')
    defaults: Optional[DefaultsConfig] = Field(default=None, description='Default settings')
    actions: List[ActionConfig] = Field(..., description='Workflow actions')
    plan: List[str] = Field(..., description='Execution plan with dependencies')

    @field_validator('plan')
    @classmethod
    def validate_plan(cls, v, info):
        """Validate that all actions in plan are defined."""
        if 'actions' in info.data:
            action_names = {action.name for action in info.data['actions']}
            for plan_item in v:
                if '<-' in plan_item:
                    action_name = plan_item.split('<-')[0].strip()
                else:
                    action_name = plan_item.strip()
                if action_name not in action_names:
                    from agent_actions.shared.exceptions import ConfigValidationError
                    raise ConfigValidationError('workflow_plan', f"Action '{action_name}' in plan not defined in actions", context={'action_name': action_name, 'plan_item': plan_item, 'defined_actions': list(action_names), 'operation': 'validate_plan'})
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
__all__ = ['ActionKind', 'Granularity', 'LoopConfig', 'ActionConfig', 'DefaultsConfig', 'DependencyEdge', 'WorkflowConfigV2']