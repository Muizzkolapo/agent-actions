"""
Unified recovery module for handling transient errors and validation failures.

This module provides a unified approach to:
- Retry: Handle transient errors (rate limits, network issues)
- Reprompt: Handle validation errors (bad JSON, schema violations)

Both share:
- Max attempts configuration
- Exhaustion behavior (continue, fail, dead_letter)
- Event tracking via RetryTracker

Key difference:
- Retry: Same request, wait with backoff, retry
- Reprompt: Modify prompt with error feedback, retry
"""

from agent_actions.recovery.recovery_config import RecoveryConfig, RecoveryMode
from agent_actions.recovery.recovery_engine import RecoveryEngine, RecoveryResult

__all__ = [
    "RecoveryConfig",
    "RecoveryMode",
    "RecoveryEngine",
    "RecoveryResult",
]
