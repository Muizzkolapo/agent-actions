"""
Batch Retry Configuration.

Configuration model for automatic retry behavior in batch processing.
Supports flexible YAML parsing (bool, string preset, or detailed dict).
"""

from typing import Any, Dict, Optional, Union
from pydantic import BaseModel, Field, field_validator


# Preset configurations for common retry strategies
RETRY_PRESETS = {
    "default": {
        "enabled": True,
        "max_attempts": 3,
    },
    "aggressive": {
        "enabled": True,
        "max_attempts": 5,
    },
    "conservative": {
        "enabled": True,
        "max_attempts": 2,
    },
    "disabled": {
        "enabled": False,
        "max_attempts": 0,
    },
}


class RetryConfig(BaseModel):
    """
    Configuration for batch retry behavior.

    Controls automatic retry of failed/missing batch records.

    Attributes:
        enabled: Whether automatic retries are enabled
        max_attempts: Maximum number of retry attempts (0 = disabled)

    Example YAML configurations:
        # Simple boolean
        retry: true

        # Preset name
        retry: aggressive

        # Detailed config
        retry:
          enabled: true
          max_attempts: 5
    """

    enabled: bool = Field(default=True, description="Enable automatic retries")
    max_attempts: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts (0 = disabled, max 10)",
    )

    @field_validator("max_attempts")
    @classmethod
    def validate_max_attempts(cls, v: int) -> int:
        """Ensure max_attempts is consistent with enabled state."""
        # If max_attempts is 0, effectively disabled
        return v

    @classmethod
    def from_yaml(cls, value: Union[bool, str, Dict[str, Any], None]) -> "RetryConfig":
        """
        Parse retry configuration from various YAML formats.

        Supports:
        - None/False: Disabled
        - True: Enabled with defaults
        - String: Preset name ('default', 'aggressive', 'conservative', 'disabled')
        - Dict: Detailed configuration

        Args:
            value: YAML configuration value

        Returns:
            RetryConfig instance

        Raises:
            ValueError: If preset name is unknown
        """
        # None or False -> disabled
        if value is None or value is False:
            return cls(enabled=False, max_attempts=0)

        # True -> enabled with defaults
        if value is True:
            return cls(enabled=True, max_attempts=3)

        # String -> preset name
        if isinstance(value, str):
            preset_name = value.lower()
            if preset_name not in RETRY_PRESETS:
                valid_presets = ", ".join(RETRY_PRESETS.keys())
                raise ValueError(f"Unknown retry preset: '{value}'. Valid presets: {valid_presets}")
            preset_config = RETRY_PRESETS[preset_name]
            return cls(**preset_config)

        # Dict -> detailed config (may include preset as base)
        if isinstance(value, dict):
            config_dict = value.copy()

            # Check if using preset as base
            preset_name = config_dict.pop("preset", None)
            if preset_name:
                if preset_name.lower() not in RETRY_PRESETS:
                    valid_presets = ", ".join(RETRY_PRESETS.keys())
                    raise ValueError(
                        f"Unknown retry preset: '{preset_name}'. Valid presets: {valid_presets}"
                    )
                # Start with preset values, override with explicit values
                base_config = RETRY_PRESETS[preset_name.lower()].copy()
                base_config.update(config_dict)
                return cls(**base_config)

            return cls(**config_dict)

        # Unknown type
        raise ValueError(f"Invalid retry configuration type: {type(value).__name__}")

    @classmethod
    def disabled(cls) -> "RetryConfig":
        """Create a disabled retry configuration."""
        return cls(enabled=False, max_attempts=0)

    @classmethod
    def default(cls) -> "RetryConfig":
        """Create default retry configuration."""
        return cls(enabled=True, max_attempts=3)

    @property
    def is_enabled(self) -> bool:
        """Check if retries are effectively enabled."""
        return self.enabled and self.max_attempts > 0

    def should_retry(self, current_attempt: int) -> bool:
        """
        Determine if another retry attempt should be made.

        Args:
            current_attempt: Current retry attempt number (0 = original batch)

        Returns:
            True if another retry should be attempted
        """
        if not self.is_enabled:
            return False
        return current_attempt < self.max_attempts

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enabled": self.enabled,
            "max_attempts": self.max_attempts,
        }


def get_retry_config(
    agent_config: Optional[Dict[str, Any]] = None,
    default_config: Optional[RetryConfig] = None,
) -> RetryConfig:
    """
    Extract retry configuration from agent config with fallback to default.

    Args:
        agent_config: Agent configuration dictionary
        default_config: Default configuration to use if not specified

    Returns:
        RetryConfig instance
    """
    if agent_config is None:
        return default_config or RetryConfig.default()

    retry_value = agent_config.get("retry")

    # Not specified -> use default
    if retry_value is None:
        return default_config or RetryConfig.default()

    # Parse from YAML value
    return RetryConfig.from_yaml(retry_value)
