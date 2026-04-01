"""Environment configuration models with validation using pydantic-settings."""

from enum import Enum

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Supported environment types."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """Supported log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EnvironmentConfig(BaseSettings):
    """Environment configuration loaded from environment variables with validation.

    The ``.env`` file is resolved by the caller (typically ``ConfigManager``)
    and passed via the ``_env_file`` constructor parameter so that the path is
    always relative to the project root — not the current working directory.
    """

    model_config = SettingsConfigDict(
        env_file=None, env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )
    openai_api_key: SecretStr | None = Field(
        default=None, description="OpenAI API Key for GPT models"
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None, description="Anthropic API Key for Claude models"
    )
    gemini_api_key: SecretStr | None = Field(default=None, description="Google Gemini API Key")
    agent_actions_env: Environment = Field(
        default=Environment.DEVELOPMENT, description="Application environment setting"
    )
    default_api_timeout: int = Field(
        default=120, ge=1, le=600, description="Default timeout for API requests in seconds"
    )
    default_max_retries: int = Field(
        default=3, ge=0, le=10, description="Maximum retries for API requests"
    )
    debug_logging: bool = Field(default=False, description="Enable debug logging")
    cache_ttl: int = Field(default=300, ge=0, description="Cache TTL in seconds (0 to disable)")
    default_batch_size: int = Field(
        default=100, ge=1, le=10000, description="Default batch size for processing"
    )
    enable_parallel_processing: bool = Field(default=True, description="Enable parallel processing")
    max_concurrency: int = Field(
        default=10, ge=1, le=100, description="Maximum number of concurrent operations"
    )
    database_url: str | None = Field(default=None, description="Database connection URL")

    @field_validator("openai_api_key", "anthropic_api_key", "gemini_api_key", mode="before")
    @classmethod
    def validate_api_keys(cls, v):
        """Validate API key format if provided."""
        if v is not None:
            key_str = v.get_secret_value() if isinstance(v, SecretStr) else v
            if len(key_str.strip()) < 10:
                raise ValueError("API key must be at least 10 characters long")
        return v

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v):
        """Validate database URL format if provided."""
        if v is not None:
            valid_prefixes = ("postgresql://", "mysql://", "sqlite:///")
            if not v.startswith(valid_prefixes):
                raise ValueError(
                    "Database URL must start with postgresql://, mysql://, or sqlite:///"
                )
        return v

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


__all__ = ["EnvironmentConfig", "Environment", "LogLevel"]
