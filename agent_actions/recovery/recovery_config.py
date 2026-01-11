"""
Recovery configuration for retry.

Handles transient error recovery (retry) for rate limits, network issues, etc.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from agent_actions.errors import ConfigValidationError


class RecoveryMode(str, Enum):
    """Type of recovery being performed."""

    RETRY = "retry"  # Transient error - same request, wait, retry


class ExhaustedBehavior(str, Enum):
    """Behavior when recovery attempts are exhausted."""

    CONTINUE = "continue"  # Create failure record, continue workflow
    FAIL = "fail"  # Raise error, workflow fails


# Valid fields for retry configuration
VALID_RETRY_FIELDS = {
    "enabled",
    "max_attempts",
    "on_exhausted",
    "backoff_base",
    "backoff_max",
}

# Valid fields for recovery configuration
VALID_RECOVERY_FIELDS = {
    "retry",
}


def _validate_retry_fields(config: Dict[str, Any]) -> None:
    """Validate retry configuration fields.

    Args:
        config: Retry configuration dict

    Raises:
        ConfigValidationError: If unknown fields are present
    """
    unknown_fields = set(config.keys()) - VALID_RETRY_FIELDS
    if unknown_fields:
        raise ConfigValidationError(
            config_key="retry",
            reason=f"Unknown retry configuration fields: {sorted(unknown_fields)}",
            context={
                "unknown_fields": sorted(unknown_fields),
                "valid_fields": sorted(VALID_RETRY_FIELDS),
                "hint": f"Valid retry fields are: {', '.join(sorted(VALID_RETRY_FIELDS))}",
            },
        )

    # Validate on_exhausted value
    on_exhausted = config.get("on_exhausted")
    if on_exhausted is not None:
        valid_behaviors = [e.value for e in ExhaustedBehavior]
        if isinstance(on_exhausted, str) and on_exhausted.lower() not in valid_behaviors:
            raise ConfigValidationError(
                config_key="on_exhausted",
                reason=f"Invalid on_exhausted value: '{on_exhausted}'",
                context={
                    "value": on_exhausted,
                    "valid_values": valid_behaviors,
                    "hint": f"Valid values are: {', '.join(valid_behaviors)}",
                },
            )

    # Validate max_attempts is positive integer
    max_attempts = config.get("max_attempts")
    if max_attempts is not None:
        if not isinstance(max_attempts, int) or max_attempts < 1:
            raise ConfigValidationError(
                config_key="max_attempts",
                reason=f"max_attempts must be a positive integer, got: {max_attempts}",
                context={
                    "value": max_attempts,
                    "hint": "max_attempts should be 1 or greater",
                },
            )

    # Validate backoff values are positive floats
    for backoff_field in ["backoff_base", "backoff_max"]:
        backoff_value = config.get(backoff_field)
        if backoff_value is not None:
            if not isinstance(backoff_value, (int, float)) or backoff_value < 0:
                raise ConfigValidationError(
                    config_key=backoff_field,
                    reason=f"{backoff_field} must be a non-negative number, got: {backoff_value}",
                    context={
                        "value": backoff_value,
                        "hint": f"{backoff_field} should be 0 or greater",
                    },
                )


def _validate_recovery_fields(config: Dict[str, Any]) -> None:
    """Validate recovery configuration fields.

    Args:
        config: Recovery configuration dict

    Raises:
        ConfigValidationError: If unknown fields are present
    """
    unknown_fields = set(config.keys()) - VALID_RECOVERY_FIELDS
    if unknown_fields:
        raise ConfigValidationError(
            config_key="recovery",
            reason=f"Unknown recovery configuration fields: {sorted(unknown_fields)}",
            context={
                "unknown_fields": sorted(unknown_fields),
                "valid_fields": sorted(VALID_RECOVERY_FIELDS),
                "hint": f"Valid recovery fields are: {', '.join(sorted(VALID_RECOVERY_FIELDS))}",
            },
        )


@dataclass
class RetryConfig:
    """Configuration for transient error retry.

    Attributes:
        enabled: Whether retry is enabled (default: True)
        max_attempts: Maximum number of retry attempts (default: 3)
        on_exhausted: Behavior when all retries fail - 'continue' or 'fail' (default: continue)
        backoff_base: Base delay in seconds for exponential backoff (default: 1.0)
        backoff_max: Maximum delay in seconds between retries (default: 60.0)
    """

    enabled: bool = True
    max_attempts: int = 3
    on_exhausted: ExhaustedBehavior = ExhaustedBehavior.CONTINUE
    backoff_base: float = 1.0  # Base delay in seconds
    backoff_max: float = 60.0  # Max delay in seconds


@dataclass
class RecoveryConfig:
    """Recovery configuration for retry.

    Example YAML configurations:

    # Disable retry
    retry: false

    # Enable with defaults
    retry: true

    # Strict mode - fail on exhaustion
    retry: strict

    # Full explicit configuration
    recovery:
      retry:
        max_attempts: 3
        backoff_base: 1.0
        backoff_max: 60.0
        on_exhausted: continue  # or 'fail'
    """

    retry: RetryConfig = field(default_factory=RetryConfig)

    @classmethod
    def from_yaml(
        cls,
        recovery_value: Optional[Union[bool, Dict[str, Any]]] = None,
        retry_value: Optional[Union[bool, str, Dict[str, Any]]] = None,
        reprompt_value: Optional[Any] = None,  # Ignored - reprompt removed
    ) -> "RecoveryConfig":
        """Parse recovery config from YAML values.

        Args:
            recovery_value: Unified recovery config (if present)
            retry_value: Retry config
            reprompt_value: Ignored (reprompt feature removed)

        Returns:
            RecoveryConfig instance

        Raises:
            ConfigValidationError: If configuration is invalid
        """
        # Handle unified recovery config
        if recovery_value is not None:
            if recovery_value is False:
                return cls(retry=RetryConfig(enabled=False))
            if recovery_value is True:
                return cls(retry=RetryConfig(enabled=True))
            if isinstance(recovery_value, dict):
                _validate_recovery_fields(recovery_value)
                retry_cfg = cls._parse_retry(recovery_value.get("retry", True))
                return cls(retry=retry_cfg)

        # Handle legacy retry config
        retry_cfg = cls._parse_retry(retry_value)
        return cls(retry=retry_cfg)

    @classmethod
    def _parse_retry(cls, value: Optional[Union[bool, str, Dict[str, Any]]]) -> RetryConfig:
        """Parse retry configuration.

        Args:
            value: Retry configuration value (bool, 'strict', or dict)

        Returns:
            RetryConfig instance

        Raises:
            ConfigValidationError: If configuration is invalid
        """
        if value is None or value is False:
            return RetryConfig(enabled=False)

        if value is True:
            return RetryConfig(enabled=True)

        if value == "strict":
            return RetryConfig(enabled=True, on_exhausted=ExhaustedBehavior.FAIL)

        if isinstance(value, str):
            raise ConfigValidationError(
                config_key="retry",
                reason=f"Invalid retry string value: '{value}'",
                context={
                    "value": value,
                    "valid_string_values": ["strict"],
                    "hint": "Use 'strict', true, false, or a configuration dict",
                },
            )

        if isinstance(value, dict):
            _validate_retry_fields(value)

            on_exhausted = value.get("on_exhausted", "continue")
            if isinstance(on_exhausted, str):
                on_exhausted = ExhaustedBehavior(on_exhausted.lower())

            return RetryConfig(
                enabled=value.get("enabled", True),
                max_attempts=value.get("max_attempts", 3),
                on_exhausted=on_exhausted,
                backoff_base=value.get("backoff_base", 1.0),
                backoff_max=value.get("backoff_max", 60.0),
            )

        raise ConfigValidationError(
            config_key="retry",
            reason=f"Invalid retry configuration type: {type(value).__name__}",
            context={
                "value": value,
                "hint": "retry should be true, false, 'strict', or a configuration dict",
            },
        )
