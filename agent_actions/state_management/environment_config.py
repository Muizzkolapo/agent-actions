"""Environment configuration models with validation using pydantic-settings."""
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_actions.errors import ConfigValidationError

class Environment(str, Enum):
    """Supported environment types."""
    DEVELOPMENT = 'development'
    STAGING = 'staging'
    PRODUCTION = 'production'

class LogLevel(str, Enum):
    """Supported log levels."""
    DEBUG = 'DEBUG'
    INFO = 'INFO'
    WARNING = 'WARNING'
    ERROR = 'ERROR'
    CRITICAL = 'CRITICAL'

class EnvironmentConfig(BaseSettings):
    """Environment configuration with validation.
    
    Loads configuration from environment variables with validation.
    Supports .env file loading and provides sensible defaults.
    """
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='forbid'
    )
    openai_api_key: Optional[SecretStr] = Field(
        default=None, description='OpenAI API Key for GPT models'
    )
    claude_api_key: Optional[SecretStr] = Field(
        default=None,
        alias='ANTHROPIC_API_KEY',
        description='Anthropic Claude API Key'
    )
    anthropic_api_key: Optional[SecretStr] = Field(
        default=None,
        description='Alternative Anthropic API Key (alias for claude_api_key)'
    )
    google_api_key: Optional[SecretStr] = Field(
        default=None, description='Google API Key for Gemini models'
    )
    agent_actions_env: Environment = Field(
        default=Environment.DEVELOPMENT,
        description='Application environment setting'
    )
    default_api_timeout: int = Field(
        default=120, ge=1, le=600,
        description='Default timeout for API requests in seconds'
    )
    default_max_retries: int = Field(
        default=3, ge=0, le=10,
        description='Maximum retries for API requests'
    )
    debug_logging: bool = Field(
        default=False, description='Enable debug logging'
    )
    cache_ttl: int = Field(
        default=300, ge=0,
        description='Cache TTL in seconds (0 to disable)'
    )
    default_batch_size: int = Field(
        default=100, ge=1, le=10000,
        description='Default batch size for processing'
    )
    enable_parallel_processing: bool = Field(
        default=True, description='Enable parallel processing'
    )
    max_concurrency: int = Field(
        default=10, ge=1, le=100,
        description='Maximum number of concurrent operations'
    )
    database_url: Optional[str] = Field(
        default=None, description='Database connection URL'
    )

    @field_validator(
        'openai_api_key', 'claude_api_key', 'anthropic_api_key', 'google_api_key',
        mode='before'
    )
    @classmethod
    def validate_api_keys(cls, v):
        """Validate API key format if provided."""
        if v is not None:
            key_str = v.get_secret_value() if isinstance(v, SecretStr) else v
            if len(key_str.strip()) < 10:
                raise ConfigValidationError(
                    'api_key_length',
                    'API key must be at least 10 characters long',
                    context={
                        'key_length': len(key_str.strip()),
                        'operation': 'validate_api_key'
                    }
                )
        return v

    @field_validator('database_url')
    @classmethod
    def validate_database_url(cls, v):
        """Validate database URL format if provided."""
        if v is not None:
            valid_prefixes = ('postgresql://', 'mysql://', 'sqlite:///')
            if not v.startswith(valid_prefixes):
                raise ConfigValidationError(
                    'database_url_format',
                    'Database URL must start with postgresql://, mysql://, or sqlite:///',
                    context={
                        'database_url': v,
                        'valid_prefixes': list(valid_prefixes),
                        'operation': 'validate_database_url'
                    }
                )
        return v

    def get_effective_claude_key(self) -> Optional[str]:
        """Get the effective Claude API key, preferring claude_api_key over anthropic_api_key."""
        key = self.claude_api_key or self.anthropic_api_key
        return key.get_secret_value() if key else None

    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.agent_actions_env == Environment.DEVELOPMENT

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.agent_actions_env == Environment.PRODUCTION

    def get_log_level(self) -> LogLevel:
        """Get appropriate log level based on environment and debug setting."""
        if self.debug_logging:
            return LogLevel.DEBUG
        if self.is_development():
            return LogLevel.INFO
        return LogLevel.WARNING

class APIConfig(BaseModel):
    """API-specific configuration extracted from environment config."""
    openai_api_key: Optional[SecretStr] = None
    claude_api_key: Optional[SecretStr] = None
    google_api_key: Optional[SecretStr] = None
    default_timeout: int = 120
    max_retries: int = 3

    @classmethod
    def from_environment(cls, env_config: EnvironmentConfig) -> 'APIConfig':
        """Create API config from environment configuration."""
        # Get claude key as string, then wrap in SecretStr if present
        claude_key_str = env_config.get_effective_claude_key()
        return cls(
            openai_api_key=env_config.openai_api_key,
            claude_api_key=SecretStr(claude_key_str) if claude_key_str else None,
            google_api_key=env_config.google_api_key,
            default_timeout=env_config.default_api_timeout,
            max_retries=env_config.default_max_retries
        )

class PerformanceConfig(BaseModel):
    """Performance-specific configuration extracted from environment config."""
    batch_size: int = 100
    enable_parallel_processing: bool = True
    max_concurrency: int = 10
    cache_ttl: int = 300

    @classmethod
    def from_environment(cls, env_config: EnvironmentConfig) -> 'PerformanceConfig':
        """Create performance config from environment configuration."""
        return cls(
            batch_size=env_config.default_batch_size,
            enable_parallel_processing=env_config.enable_parallel_processing,
            max_concurrency=env_config.max_concurrency,
            cache_ttl=env_config.cache_ttl
        )

__all__ = ['EnvironmentConfig', 'APIConfig', 'PerformanceConfig', 'Environment', 'LogLevel']
