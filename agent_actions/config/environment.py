"""Environment configuration models with validation using pydantic-settings."""

from enum import Enum

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Supported environment types."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


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

    @field_validator("openai_api_key", "anthropic_api_key", "gemini_api_key", mode="before")
    @classmethod
    def validate_api_keys(cls, v):
        """Validate API key format if provided."""
        if v is not None:
            key_str = v.get_secret_value() if isinstance(v, SecretStr) else v
            if len(key_str.strip()) < 10:
                raise ValueError("API key must be at least 10 characters long")
        return v

    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.agent_actions_env == Environment.DEVELOPMENT

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.agent_actions_env == Environment.PRODUCTION


__all__ = ["EnvironmentConfig", "Environment"]
