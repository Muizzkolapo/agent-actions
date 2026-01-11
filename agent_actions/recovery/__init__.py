"""
Unified recovery module for handling transient errors.

This module provides retry handling for transient errors (rate limits, network issues).

Features:
- Max attempts configuration
- Exhaustion behavior (continue or fail)
- Retry metadata embedded in output records (_retry_metadata)

The retry state is tracked in each output record's _retry_metadata field, including:
- was_retried: Whether the record was retried
- retry_attempts: Number of retry attempts made
- error_type: Type of error that triggered retry
- error_message: Error message from the retry
- exhausted: Whether max attempts were reached
"""

from agent_actions.recovery.recovery_config import RecoveryConfig, RecoveryMode
from agent_actions.recovery.recovery_engine import RecoveryEngine, RecoveryResult

__all__ = [
    "RecoveryConfig",
    "RecoveryMode",
    "RecoveryEngine",
    "RecoveryResult",
]
