from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional, Dict, Any, Literal
from enum import Enum


class FilterScope(str, Enum):
    """Scope for WHERE clause filtering."""
    ITEM = "item"
    AGENT = "agent"


class WhereClauseConfig(BaseModel):
    """Configuration for WHERE clause filtering."""
    
    clause: str = Field(
        ..., 
        description="SQL-like WHERE clause for filtering",
        min_length=1,
        max_length=10000
    )
    scope: FilterScope = Field(
        default=FilterScope.ITEM,
        description="Filtering scope: 'item' for individual items, 'agent' for entire agent execution"
    )
    passthrough_on_empty: bool = Field(
        default=True,
        description="Pass data through if no matches found"
    )
    passthrough_on_error: bool = Field(
        default=True,
        description="Pass data through if evaluation error occurs"
    )
    cache_enabled: bool = Field(
        default=True,
        description="Enable caching of parsed WHERE clauses for performance"
    )
    
    @field_validator('clause')
    @classmethod
    def validate_clause(cls, v):
        """Validate the WHERE clause syntax."""
        if not v or not v.strip():
            raise ValueError("WHERE clause cannot be empty")
        
        # Basic safety checks
        dangerous_patterns = [
            '__import__', 'exec', 'eval', 'compile', 'open', 'file',
            'input', 'raw_input', 'reload', 'vars', 'globals', 'locals',
            'dir', 'hasattr', 'getattr', 'setattr', 'delattr'
        ]
        
        clause_lower = v.lower()
        for pattern in dangerous_patterns:
            if pattern in clause_lower:
                raise ValueError(f"WHERE clause contains potentially dangerous operation: {pattern}")
        
        return v
    
    model_config = ConfigDict(extra="forbid")


class SkipConditionConfig(BaseModel):
    """Configuration for agent skip conditions (safe replacement for eval-based skip_if)."""
    
    condition_type: Literal["previous_outputs_empty", "previous_outputs_count", "field_condition", "custom"] = Field(
        description="Type of skip condition"
    )
    
    # For previous_outputs_empty and previous_outputs_count
    agent_name: Optional[str] = Field(
        default=None,
        description="Name of the agent to check outputs for"
    )
    
    # For previous_outputs_count
    threshold: Optional[int] = Field(
        default=None,
        description="Threshold for count-based conditions"
    )
    comparison: Optional[Literal["==", "!=", "<", "<=", ">", ">="]] = Field(
        default="==",
        description="Comparison operator for threshold"
    )
    
    # For field_condition
    field_path: Optional[str] = Field(
        default=None,
        description="Path to field in previous outputs (dot notation)"
    )
    expected_value: Optional[Any] = Field(
        default=None,
        description="Expected value for field condition"
    )
    
    # For custom conditions (safe expression evaluation)
    expression: Optional[str] = Field(
        default=None,
        description="Safe expression for custom conditions (no eval())"
    )
    
    @field_validator('expression')
    @classmethod
    def validate_expression(cls, v, info):
        """Validate custom expressions for safety."""
        if v and info.data.get('condition_type') == 'custom':
            # Basic safety validation
            dangerous_patterns = [
                '__import__', 'exec', 'eval', 'compile', 'open', 'file',
                'input', 'raw_input', 'reload', 'vars', 'globals', 'locals'
            ]
            
            expr_lower = v.lower()
            for pattern in dangerous_patterns:
                if pattern in expr_lower:
                    raise ValueError(f"Expression contains potentially dangerous operation: {pattern}")
        
        return v
    
    model_config = ConfigDict(extra="forbid")


class DefaultAgentConfig(BaseModel):
    """Default settings applied to each agent configuration."""

    api_key: Optional[str] = None
    model_name: Optional[str] = None
    chunk_config: Optional[Dict[str, Any]] = None
    is_operational: bool = True
    run_mode: str = 'online'

    model_config = ConfigDict(extra="allow")


class AgentConfig(BaseModel):
    """Schema for an individual agent configuration entry."""

    agent_type: str
    name: Optional[str] = None
    model_name: Optional[str] = None
    model_vendor: Optional[str] = Field(
        default=None, 
        description="Model vendor/provider: 'openai', 'gemini', 'anthropic', 'groq', or 'tool'"
    )
    api_key: Optional[str] = None
    code_path: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    parent: List[str] = Field(default_factory=list)
    prompt: Optional[str] = None
    schema_name: Optional[str] = None
    chunk_config: Dict[str, Any] = Field(default_factory=dict)
    side_collection: List[str] = Field(default_factory=list)
    is_operational: bool = True
    use_few_shot_samples: int = Field(default=0, ge=0)
    ephemeral: Optional[bool] = None
    add_dispatch: Optional[bool] = None
    run_mode: str = 'online'
    data_source: Optional[str] = None
    
    # Anthropic-specific configuration options
    anthropic_version: Optional[str] = Field(
        default=None,
        description="API version header for Anthropic requests (e.g., '2023-06-01')"
    )
    enable_prompt_caching: Optional[bool] = Field(
        default=None,
        description="Enable Anthropic's prompt caching feature for improved performance"
    )
    
    # Legacy filtering support (deprecated)
    conditional_clause: Optional[str] = Field(
        default=None,
        description="Legacy conditional clause (deprecated, use where_clause instead)"
    )
    skip_if: Optional[str] = Field(
        default=None,
        description="Legacy skip condition (deprecated, use skip_condition instead)"
    )
    
    # New WHERE clause filtering
    where_clause: Optional[WhereClauseConfig] = Field(
        default=None,
        description="WHERE clause configuration for advanced filtering"
    )
    
    # Safe skip conditions
    skip_condition: Optional[SkipConditionConfig] = Field(
        default=None,
        description="Safe skip condition configuration"
    )
    
    # Security and performance settings
    max_execution_time: Optional[int] = Field(
        default=300,
        description="Maximum execution time in seconds"
    )
    enable_caching: bool = Field(
        default=True,
        description="Enable caching for performance"
    )

    model_config = ConfigDict(extra="allow")


class EnhancedAgentConfig(AgentConfig):
    """Extended agent configuration with filtering options."""

    conditional_clause: Optional[str] = None
    where_clause: Optional[WhereClauseConfig] = None
    skip_if: Optional[str] = None


__all__ = [
    "DefaultAgentConfig",
    "AgentConfig",
    "WhereClauseConfig",
    "EnhancedAgentConfig",
    "FilterScope",
    "SkipConditionConfig",
]
