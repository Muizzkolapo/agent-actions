"""
Enhanced configuration schema with production-grade WHERE clause support.
Extends existing configuration with comprehensive WHERE clause features.
"""
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any, Union
from enum import Enum

from .config_schema import AgentConfig


class WhereClauseScope(str, Enum):
    """Scope for WHERE clause evaluation."""
    ITEM = "item"
    AGENT = "agent"
    BATCH = "batch"


class SecurityLevel(str, Enum):
    """Security levels for WHERE clause evaluation."""
    STRICT = "strict"
    STANDARD = "standard"
    PERMISSIVE = "permissive"


class WhereClauseConfig(BaseModel):
    """Production-grade WHERE clause configuration."""
    
    clause: str = Field(..., description="SQL-like WHERE clause")
    scope: WhereClauseScope = Field(default=WhereClauseScope.ITEM, description="Evaluation scope")
    passthrough_on_empty: bool = Field(default=True, description="Pass data through if no matches")
    passthrough_on_error: bool = Field(default=False, description="Pass data through on evaluation errors")
    max_evaluation_time_ms: float = Field(default=100.0, description="Maximum evaluation time in milliseconds")
    enable_caching: bool = Field(default=True, description="Enable result caching")
    security_level: SecurityLevel = Field(default=SecurityLevel.STANDARD, description="Security level")
    allowed_fields: Optional[List[str]] = Field(default=None, description="Allowed field names for security")
    max_conditions: Optional[int] = Field(default=None, description="Maximum number of conditions")
    
    @validator('clause')
    def validate_clause(cls, v):
        """Validate WHERE clause string."""
        if not v or not v.strip():
            raise ValueError("WHERE clause cannot be empty")
        if len(v) > 2000:  # Maximum reasonable length
            raise ValueError("WHERE clause too long (max 2000 characters)")
        return v.strip()
    
    @validator('max_evaluation_time_ms')
    def validate_evaluation_time(cls, v):
        """Validate evaluation time limits."""
        if v <= 0:
            raise ValueError("Evaluation time must be positive")
        if v > 10000:  # 10 seconds max
            raise ValueError("Evaluation time too long (max 10 seconds)")
        return v


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration."""
    
    enabled: bool = Field(default=True, description="Enable circuit breaker")
    failure_threshold: int = Field(default=3, description="Failures before opening circuit")
    recovery_timeout: float = Field(default=30.0, description="Time before attempting recovery (seconds)")
    success_threshold: int = Field(default=2, description="Successes needed to close circuit")
    timeout: float = Field(default=1.0, description="Operation timeout (seconds)")


class RetryConfig(BaseModel):
    """Retry configuration."""
    
    enabled: bool = Field(default=True, description="Enable retry mechanism")
    max_attempts: int = Field(default=2, description="Maximum retry attempts")
    base_delay: float = Field(default=0.1, description="Base delay between retries (seconds)")
    max_delay: float = Field(default=2.0, description="Maximum delay between retries (seconds)")
    exponential_backoff: bool = Field(default=True, description="Use exponential backoff")


class MonitoringConfig(BaseModel):
    """Monitoring and observability configuration."""
    
    enable_metrics: bool = Field(default=True, description="Enable Prometheus metrics")
    enable_tracing: bool = Field(default=True, description="Enable distributed tracing")
    enable_debug_logging: bool = Field(default=False, description="Enable debug logging")
    log_level: str = Field(default="INFO", description="Logging level")
    correlation_tracking: bool = Field(default=True, description="Enable request correlation")


class PerformanceConfig(BaseModel):
    """Performance optimization configuration."""
    
    enable_caching: bool = Field(default=True, description="Enable result caching")
    cache_ttl_seconds: int = Field(default=300, description="Cache TTL in seconds")
    batch_size: int = Field(default=100, description="Batch processing size")
    parallel_processing: bool = Field(default=False, description="Enable parallel processing")
    max_concurrent_evaluations: int = Field(default=10, description="Max concurrent evaluations")


class FeatureFlagConfig(BaseModel):
    """Feature flag configuration."""
    
    where_clause_enabled: bool = Field(default=False, description="Enable WHERE clause functionality")
    advanced_operators: bool = Field(default=False, description="Enable advanced operators (OR, LIKE)")
    security_mode: bool = Field(default=True, description="Enable enhanced security checks")
    debug_mode: bool = Field(default=False, description="Enable debug mode")


class ProductionWhereClauseConfig(BaseModel):
    """Complete production WHERE clause configuration."""
    
    where_clause: WhereClauseConfig
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    feature_flags: FeatureFlagConfig = Field(default_factory=FeatureFlagConfig)


class LegacySkipCondition(BaseModel):
    """Legacy skip condition for backward compatibility."""
    
    condition: str = Field(..., description="Skip condition expression")
    mode: str = Field(default="python", description="Evaluation mode")
    safe_mode: bool = Field(default=True, description="Use safe evaluation")


class EnhancedAgentConfig(AgentConfig):
    """Enhanced agent configuration with production WHERE clause support."""
    
    # Legacy support (backward compatibility)
    conditional_clause: Optional[str] = Field(default=None, description="Legacy conditional clause")
    skip_if: Optional[str] = Field(default=None, description="Simple agent-level skip condition")
    
    # New WHERE clause support
    where_clause: Optional[ProductionWhereClauseConfig] = Field(
        default=None, 
        description="Production WHERE clause configuration"
    )
    
    # Simple WHERE clause (for basic use cases)
    simple_where: Optional[str] = Field(
        default=None, 
        description="Simple WHERE clause string (uses default settings)"
    )
    
    # Legacy skip condition (structured)
    skip_condition: Optional[LegacySkipCondition] = Field(
        default=None,
        description="Legacy skip condition configuration"
    )
    
    # Production settings
    security_level: SecurityLevel = Field(
        default=SecurityLevel.STANDARD,
        description="Security level for this agent"
    )
    
    enable_monitoring: bool = Field(
        default=True,
        description="Enable monitoring for this agent"
    )
    
    @validator('where_clause', 'simple_where', 'conditional_clause', 'skip_if')
    def validate_exclusive_conditions(cls, v, values):
        """Ensure only one type of condition is specified."""
        condition_fields = ['where_clause', 'simple_where', 'conditional_clause', 'skip_if']
        specified_conditions = sum(
            1 for field in condition_fields 
            if values.get(field) is not None or (field == 'where_clause' and v is not None)
        )
        
        if specified_conditions > 1:
            raise ValueError(
                "Only one of where_clause, simple_where, conditional_clause, or skip_if can be specified"
            )
        
        return v
    
    def get_effective_where_clause_config(self) -> Optional[WhereClauseConfig]:
        """Get the effective WHERE clause configuration."""
        if self.where_clause:
            return self.where_clause.where_clause
        elif self.simple_where:
            return WhereClauseConfig(clause=self.simple_where)
        else:
            return None
    
    def has_where_clause(self) -> bool:
        """Check if agent has any WHERE clause configuration."""
        return any([
            self.where_clause,
            self.simple_where,
            self.conditional_clause,
            self.skip_if
        ])
    
    def is_legacy_configuration(self) -> bool:
        """Check if this uses legacy configuration."""
        return any([
            self.conditional_clause,
            self.skip_if,
            self.skip_condition
        ])


class WorkflowConfig(BaseModel):
    """Enhanced workflow configuration."""
    
    agents: List[EnhancedAgentConfig]
    default_settings: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Default settings applied to all agents"
    )
    global_where_clause: Optional[ProductionWhereClauseConfig] = Field(
        default=None,
        description="Global WHERE clause applied to all agents"
    )
    monitoring: MonitoringConfig = Field(
        default_factory=MonitoringConfig,
        description="Global monitoring configuration"
    )
    performance: PerformanceConfig = Field(
        default_factory=PerformanceConfig,
        description="Global performance configuration"
    )
    
    @validator('agents')
    def validate_agents(cls, v):
        """Validate agent configurations."""
        if not v:
            raise ValueError("At least one agent must be specified")
        
        # Check for duplicate agent names
        names = [agent.name for agent in v if agent.name]
        if len(names) != len(set(names)):
            raise ValueError("Agent names must be unique")
        
        return v


# Migration helpers
def migrate_legacy_config(legacy_config: Dict[str, Any]) -> EnhancedAgentConfig:
    """
    Migrate legacy configuration to enhanced configuration.
    
    Args:
        legacy_config: Legacy configuration dictionary
        
    Returns:
        Enhanced agent configuration
    """
    enhanced_config = legacy_config.copy()
    
    # Convert conditional_clause to simple WHERE clause if possible
    if 'conditional_clause' in enhanced_config:
        conditional = enhanced_config['conditional_clause']
        
        # Try to convert simple conditions
        if 'row_content.get("questionable") != "Low Value"' in conditional:
            enhanced_config['simple_where'] = 'questionable != "Low Value"'
            enhanced_config.pop('conditional_clause', None)
    
    return EnhancedAgentConfig(**enhanced_config)


def create_simple_where_clause_config(clause: str, **kwargs) -> ProductionWhereClauseConfig:
    """
    Create a simple WHERE clause configuration with default production settings.
    
    Args:
        clause: WHERE clause string
        **kwargs: Additional configuration options
        
    Returns:
        Production WHERE clause configuration
    """
    where_config = WhereClauseConfig(clause=clause, **kwargs)
    
    return ProductionWhereClauseConfig(
        where_clause=where_config,
        circuit_breaker=CircuitBreakerConfig(),
        retry=RetryConfig(),
        monitoring=MonitoringConfig(),
        performance=PerformanceConfig(),
        feature_flags=FeatureFlagConfig(where_clause_enabled=True)
    )


# Configuration validation
def validate_where_clause_syntax(clause: str) -> List[str]:
    """
    Validate WHERE clause syntax and return list of issues.
    
    Args:
        clause: WHERE clause to validate
        
    Returns:
        List of validation issues (empty if valid)
    """
    issues = []
    
    if not clause or not clause.strip():
        issues.append("WHERE clause cannot be empty")
        return issues
    
    # Basic syntax checks
    if len(clause) > 1000:
        issues.append("WHERE clause too long (max 1000 characters)")
    
    # Check for dangerous patterns
    dangerous_patterns = [
        '__import__', 'eval', 'exec', 'open', 'file',
        'subprocess', 'os.', 'sys.', 'globals', 'locals'
    ]
    
    for pattern in dangerous_patterns:
        if pattern in clause.lower():
            issues.append(f"Potentially dangerous pattern detected: {pattern}")
    
    # Check for unbalanced quotes
    single_quotes = clause.count("'")
    double_quotes = clause.count('"')
    
    if single_quotes % 2 != 0:
        issues.append("Unbalanced single quotes")
    
    if double_quotes % 2 != 0:
        issues.append("Unbalanced double quotes")
    
    return issues


# Example configurations
def get_example_configurations() -> Dict[str, EnhancedAgentConfig]:
    """Get example configurations for different use cases."""
    
    examples = {}
    
    # Basic filtering
    examples['basic_filter'] = EnhancedAgentConfig(
        agent_type="ContentFilter",
        simple_where='questionable != "Low Value"'
    )
    
    # Advanced filtering with full configuration
    examples['advanced_filter'] = EnhancedAgentConfig(
        agent_type="AdvancedFilter",
        where_clause=ProductionWhereClauseConfig(
            where_clause=WhereClauseConfig(
                clause='status == "active" AND score >= 75 AND metadata.source IN ["trusted", "verified"]',
                scope=WhereClauseScope.ITEM,
                security_level=SecurityLevel.STRICT
            ),
            monitoring=MonitoringConfig(
                enable_debug_logging=True
            ),
            performance=PerformanceConfig(
                batch_size=50,
                parallel_processing=True
            )
        )
    )
    
    # Agent-level conditional
    examples['agent_conditional'] = EnhancedAgentConfig(
        agent_type="ConditionalAgent",
        where_clause=ProductionWhereClauseConfig(
            where_clause=WhereClauseConfig(
                clause='previous_outputs["ExtractionAgent"]["count"] > 5',
                scope=WhereClauseScope.AGENT
            )
        )
    )
    
    # Legacy compatibility
    examples['legacy_compatible'] = EnhancedAgentConfig(
        agent_type="LegacyAgent",
        conditional_clause='row_content.get("status") == "active"',
        security_level=SecurityLevel.PERMISSIVE
    )
    
    return examples