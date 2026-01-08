"""
Unified recovery configuration for retry and reprompt.

Supports both transient error recovery (retry) and validation error
recovery (reprompt) with shared configuration patterns.

All options must be explicitly configured - no implicit presets.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class RecoveryMode(str, Enum):
    """Type of recovery being performed."""

    RETRY = "retry"  # Transient error - same request, wait, retry
    REPROMPT = "reprompt"  # Validation error - modify prompt, retry


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
class RepromptConfig:
    """Configuration for validation error reprompt.

    All options must be explicitly set in YAML config:
        reprompt:
          max_attempts: 3
          json_repair: true
          use_llm_critique: false
          critique_after_attempt: 2
          on_exhausted: continue
    """

    enabled: bool = False  # Must be explicitly enabled
    max_attempts: int = 3
    on_exhausted: ExhaustedBehavior = ExhaustedBehavior.CONTINUE
    json_repair: bool = True
    use_llm_critique: bool = False
    use_self_reflection: bool = False
    critique_after_attempt: int = 2
    constraints: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class RecoveryConfig:
    """Unified recovery configuration for both retry and reprompt.

    All options must be explicitly configured - no presets.

    Example YAML configurations:

    # Enable retry only (reprompt disabled by default)
    retry: true

    # Enable reprompt with explicit options
    reprompt:
      max_attempts: 3
      json_repair: true
      use_llm_critique: false
      critique_after_attempt: 2
      on_exhausted: continue

    # Full explicit configuration
    recovery:
      retry:
        max_attempts: 3
        backoff_base: 1.0
        backoff_max: 60.0
        on_exhausted: dead_letter
      reprompt:
        max_attempts: 4
        json_repair: true
        use_llm_critique: true
        critique_after_attempt: 2
        on_exhausted: continue
    """

    retry: RetryConfig = field(default_factory=RetryConfig)
    reprompt: RepromptConfig = field(default_factory=RepromptConfig)

    @classmethod
    def from_yaml(
        cls,
        recovery_value: Optional[Union[bool, Dict[str, Any]]] = None,
        retry_value: Optional[Union[bool, str, Dict[str, Any]]] = None,
        reprompt_value: Optional[Union[bool, str, Dict[str, Any]]] = None,
    ) -> "RecoveryConfig":
        """Parse recovery config from YAML values.

        Supports multiple formats:
        1. Unified: recovery: true | false | {retry: ..., reprompt: ...}
        2. Legacy: retry: ... and reprompt: ... as separate keys

        Args:
            recovery_value: Unified recovery config (if present)
            retry_value: Legacy retry config
            reprompt_value: Legacy reprompt config

        Returns:
            RecoveryConfig instance
        """
        # Handle unified recovery config
        if recovery_value is not None:
            if recovery_value is False:
                return cls(
                    retry=RetryConfig(enabled=False),
                    reprompt=RepromptConfig(enabled=False),
                )
            if recovery_value is True:
                return cls(
                    retry=RetryConfig(enabled=True),
                    reprompt=RepromptConfig(enabled=True),
                )
            if isinstance(recovery_value, dict):
                retry_cfg = cls._parse_retry(recovery_value.get("retry", True))
                reprompt_cfg = cls._parse_reprompt(recovery_value.get("reprompt", True))
                return cls(retry=retry_cfg, reprompt=reprompt_cfg)

        # Handle legacy separate configs
        retry_cfg = cls._parse_retry(retry_value)
        reprompt_cfg = cls._parse_reprompt(reprompt_value)
        return cls(retry=retry_cfg, reprompt=reprompt_cfg)

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

    @classmethod
    def _parse_reprompt(cls, value: Optional[Union[bool, str, Dict[str, Any]]]) -> RepromptConfig:
        """Parse reprompt configuration.

        Requires explicit configuration - no presets allowed.

        Valid formats:
            reprompt: false  # disabled
            reprompt:
              max_attempts: 3
              json_repair: true
              use_llm_critique: false
              critique_after_attempt: 2
              on_exhausted: continue
        """
        if value is None or value is False:
            return RepromptConfig(enabled=False)

        if value is True:
            raise ValueError(
                "reprompt: true is not allowed. You must explicitly configure reprompt options:\n"
                "reprompt:\n"
                "  max_attempts: 3\n"
                "  json_repair: true\n"
                "  use_llm_critique: false\n"
                "  critique_after_attempt: 2\n"
                "  on_exhausted: continue"
            )

        if isinstance(value, str):
            raise ValueError(
                f"reprompt: '{value}' is not allowed. Presets have been removed.\n"
                "You must explicitly configure reprompt options:\n"
                "reprompt:\n"
                "  max_attempts: 3\n"
                "  json_repair: true\n"
                "  use_llm_critique: false\n"
                "  critique_after_attempt: 2\n"
                "  on_exhausted: continue"
            )

        if isinstance(value, dict):
            on_exhausted = value.get("on_exhausted", "continue")
            if isinstance(on_exhausted, str):
                on_exhausted = ExhaustedBehavior(on_exhausted.lower())

            return RepromptConfig(
                enabled=value.get("enabled", True),
                max_attempts=value.get("max_attempts", 3),
                on_exhausted=on_exhausted,
                json_repair=value.get("json_repair", True),
                use_llm_critique=value.get("use_llm_critique", False),
                use_self_reflection=value.get("use_self_reflection", False),
                critique_after_attempt=value.get("critique_after_attempt", 2),
                constraints=value.get("constraints", []),
            )

        return RepromptConfig(enabled=False)
