"""
Recovery configuration for retry.

Handles transient error recovery (retry) for rate limits, network issues, etc.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Union


class RecoveryMode(str, Enum):
    """Type of recovery being performed."""

    RETRY = "retry"  # Transient error - same request, wait, retry


class ExhaustedBehavior(str, Enum):
    """Behavior when recovery attempts are exhausted."""

    CONTINUE = "continue"  # Drop failed record, continue workflow
    FAIL = "fail"  # Raise error, workflow fails
    DEAD_LETTER = "dead_letter"  # Write to .failed.json, continue


@dataclass
class RetryConfig:
    """Configuration for transient error retry."""

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

    # Full explicit configuration
    retry:
      max_attempts: 3
      backoff_base: 1.0
      backoff_max: 60.0
      on_exhausted: dead_letter
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
        """
        # Handle unified recovery config
        if recovery_value is not None:
            if recovery_value is False:
                return cls(retry=RetryConfig(enabled=False))
            if recovery_value is True:
                return cls(retry=RetryConfig(enabled=True))
            if isinstance(recovery_value, dict):
                retry_cfg = cls._parse_retry(recovery_value.get("retry", True))
                return cls(retry=retry_cfg)

        # Handle legacy retry config
        retry_cfg = cls._parse_retry(retry_value)
        return cls(retry=retry_cfg)

    @classmethod
    def _parse_retry(cls, value: Optional[Union[bool, str, Dict[str, Any]]]) -> RetryConfig:
        """Parse retry configuration."""
        if value is None or value is False:
            return RetryConfig(enabled=False)

        if value is True:
            return RetryConfig(enabled=True)

        if value == "strict":
            return RetryConfig(enabled=True, on_exhausted=ExhaustedBehavior.FAIL)

        if isinstance(value, dict):
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

        return RetryConfig(enabled=True)
