from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional, Dict, Any, Literal, Union
from enum import Enum

class FilterScope(str, Enum):
    """Scope for WHERE clause filtering."""
    ITEM = 'item'
    AGENT = 'agent'

class WhereClauseBehavior(str, Enum):
    """Behavior when WHERE clause condition fails."""
    SKIP = 'skip'
    FILTER = 'filter'

class WhereClauseConfig(BaseModel):
    """Configuration for WHERE clause filtering."""
    clause: str = Field(..., description='SQL-like WHERE clause for filtering', max_length=10000)
    scope: FilterScope = Field(default=FilterScope.ITEM, description="Filtering scope: 'item' for individual items, 'agent' for entire agent execution")
    passthrough_on_empty: bool = Field(default=True, description='Pass data through if no matches found')
    passthrough_on_error: bool = Field(default=True, description='Pass data through if evaluation error occurs')
    cache_enabled: bool = Field(default=True, description='Enable caching of parsed WHERE clauses for performance')
    behavior: WhereClauseBehavior = Field(default=WhereClauseBehavior.FILTER, description="Behavior when condition fails: 'skip' (passthrough) or 'filter' (remove)")

    @field_validator('clause')
    @classmethod
    def validate_clause(cls, v):
        """Validate the WHERE clause syntax."""
        from agent_actions.shared.exceptions import ValidationError
        if v is not None and (not v or not v.strip()):
            raise ValidationError('WHERE clause cannot be empty', context={'clause': v, 'operation': 'validate_where_clause'})
        dangerous_patterns = ['__import__', 'exec', 'eval', 'compile', 'open', 'file', 'input', 'raw_input', 'reload', 'vars', 'globals', 'locals', 'dir', 'hasattr', 'getattr', 'setattr', 'delattr']
        clause_lower = v.lower()
        for pattern in dangerous_patterns:
            if pattern in clause_lower:
                raise ValidationError(f'WHERE clause contains potentially dangerous operation: {pattern}', context={'clause': v, 'dangerous_pattern': pattern, 'operation': 'validate_where_clause'})
        return v
    model_config = ConfigDict(extra='forbid')

class SkipConditionConfig(BaseModel):
    """Configuration for agent skip conditions (safe replacement for eval-based skip_if)."""
    condition_type: Literal['previous_outputs_empty', 'previous_outputs_count', 'field_condition', 'custom'] = Field(description='Type of skip condition')
    agent_name: Optional[str] = Field(default=None, description='Name of the agent to check outputs for')
    threshold: Optional[int] = Field(default=None, description='Threshold for count-based conditions')
    comparison: Optional[Literal['==', '!=', '<', '<=', '>', '>=']] = Field(default='==', description='Comparison operator for threshold')
    field_path: Optional[str] = Field(default=None, description='Path to field in previous outputs (dot notation)')
    expected_value: Optional[Any] = Field(default=None, description='Expected value for field condition')
    expression: Optional[str] = Field(default=None, description='Safe expression for custom conditions (no eval())')

    @field_validator('expression')
    @classmethod
    def validate_expression(cls, v, info):
        """Validate custom expressions for safety."""
        from agent_actions.shared.exceptions import ValidationError
        if v and info.data.get('condition_type') == 'custom':
            dangerous_patterns = ['__import__', 'exec', 'eval', 'compile', 'open', 'file', 'input', 'raw_input', 'reload', 'vars', 'globals', 'locals']
            expr_lower = v.lower()
            for pattern in dangerous_patterns:
                if pattern in expr_lower:
                    raise ValidationError(f'Expression contains potentially dangerous operation: {pattern}', context={'expression': v, 'dangerous_pattern': pattern, 'operation': 'validate_skip_condition'})
        return v
    model_config = ConfigDict(extra='forbid')

class DefaultAgentConfig(BaseModel):
    """Default settings applied to each agent configuration."""
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    chunk_config: Optional[Dict[str, Any]] = None
    is_operational: bool = True
    run_mode: str = 'online'
    model_config = ConfigDict(extra='allow')

class AgentConfig(BaseModel):
    """Schema for an individual agent configuration entry."""
    agent_type: str
    name: Optional[str] = None
    model_name: Optional[str] = None
    model_vendor: Optional[str] = Field(default=None, description="Model vendor/provider: 'openai', 'gemini', 'anthropic', 'groq', or 'tool'")
    api_key: Optional[str] = None
    code_path: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    parent: List[str] = Field(default_factory=list)
    prompt: Optional[str] = None
    schema_name: Optional[str] = None
    chunk_config: Dict[str, Any] = Field(default_factory=dict)
    observe: List[str] = Field(default_factory=list)
    drops: List[str] = Field(default_factory=list)
    is_operational: bool = True
    few_shot: int = Field(default=0, ge=0)
    ephemeral: Optional[bool] = None
    add_dispatch: Optional[bool] = None
    run_mode: str = 'online'
    data_source: Optional[str] = None
    json_mode: bool = Field(default=True, description='Enable JSON mode for structured output')
    prompt_debug: bool = Field(default=False, description='Enable debug output showing prompts being sent to the agent')
    anthropic_version: Optional[str] = Field(default=None, description="API version header for Anthropic requests (e.g., '2023-06-01')")
    enable_prompt_caching: Optional[bool] = Field(default=None, description="Enable Anthropic's prompt caching feature for improved performance")
    conditional_clause: Optional[str] = Field(default=None, description='Legacy conditional clause (deprecated, use where_clause instead)')
    skip_if: Optional[str] = Field(default=None, description='Legacy skip condition (deprecated, use skip_condition instead)')
    where_clause: Optional[WhereClauseConfig] = Field(default=None, description='WHERE clause configuration for advanced filtering')
    skip_condition: Optional[SkipConditionConfig] = Field(default=None, description='Safe skip condition configuration')
    max_execution_time: Optional[int] = Field(default=300, description='Maximum execution time in seconds')
    enable_caching: bool = Field(default=True, description='Enable caching for performance')

    def input_signature(self, dependency_configs: Dict[str, Union['AgentConfig', Dict[str, Any]]], schema_registry: Optional[Dict[str, Any]]=None) -> 'InputSignature':
        """Get input signature showing what fields this agent requires.
        
        Args:
            dependency_configs: Map of dependency names to their configurations
            schema_registry: Optional registry for resolving schema references
            
        Returns:
            InputSignature with field requirements from dependencies, source, etc.
        """
        from agent_actions.state_management.signature_computer import SignatureComputer
        agent_dict = self.model_dump()
        dep_dicts = {}
        for name, config in dependency_configs.items():
            if hasattr(config, 'model_dump'):
                dep_dicts[name] = config.model_dump()
            else:
                dep_dicts[name] = config
        return SignatureComputer.compute_input_signature(agent_dict, dep_dicts, schema_registry)

    def output_signature(self, schema_registry: Optional[Dict[str, Any]]=None) -> 'OutputSignature':
        """Get output signature showing what fields this agent provides.
        
        Args:
            schema_registry: Optional registry for resolving schema references
            
        Returns:
            OutputSignature with available fields from schema, observe, drops
        """
        from agent_actions.state_management.signature_computer import SignatureComputer
        agent_dict = self.model_dump()
        return SignatureComputer.compute_output_signature(agent_dict, schema_registry)
    model_config = ConfigDict(extra='allow')

class EnhancedAgentConfig(AgentConfig):
    """Extended agent configuration with filtering options."""
    conditional_clause: Optional[str] = None
    where_clause: Optional[WhereClauseConfig] = None
    skip_if: Optional[str] = None
__all__ = ['DefaultAgentConfig', 'AgentConfig', 'WhereClauseConfig', 'EnhancedAgentConfig', 'FilterScope', 'SkipConditionConfig']