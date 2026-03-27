"""
Failure Injection Module - Testing infrastructure for retry/recovery.

This module provides a clean, separable layer for injecting failures
during testing. It can be completely removed by:
1. Deleting this file
2. Removing the import and function calls from client files

Configuration via environment variables:
    FAILURE_INJECTION_RATE=0.3      # 30% of operations will fail
    FAILURE_INJECTION_IDS=id1,id2   # Specific custom_ids to fail (batch only)
    FAILURE_INJECTION_SEED=42       # Reproducible failures for testing

Usage in batch clients:
    from .failure_injection import should_skip_record

    if should_skip_record(custom_id):
        continue  # Skip this record to simulate missing result

Usage in online clients:
    from .failure_injection import maybe_raise_error

    maybe_raise_error()  # Call before API request

See also: agent_actions.llm.providers.ollama.failure_injection (count-based injection)
"""

import logging
import os
import random

logger = logging.getLogger(__name__)


class FailureInjector:
    """
    Centralized failure injection for testing retry infrastructure.

    Supports two modes:
    1. Record skipping (batch): Returns True for records that should be omitted
    2. Error raising (online): Raises exceptions to trigger retry logic
    """

    def __init__(self):
        """Initialize from environment variables."""
        self._rate: float = float(os.getenv("FAILURE_INJECTION_RATE", "0"))
        self._ids: set[str] = self._parse_ids(os.getenv("FAILURE_INJECTION_IDS", ""))
        self._seed: int | None = self._parse_seed(os.getenv("FAILURE_INJECTION_SEED", ""))
        self._rng: random.Random = random.Random(self._seed)

        if self.is_enabled():
            logger.info(
                "Failure injection ENABLED: rate=%.2f, ids=%s, seed=%s",
                self._rate,
                self._ids or "(random)",
                self._seed,
            )

    @staticmethod
    def _parse_ids(ids_str: str) -> set[str]:
        """Parse comma-separated IDs into a set."""
        return {id_.strip() for id_ in ids_str.split(",") if id_.strip()}

    @staticmethod
    def _parse_seed(seed_str: str) -> int | None:
        """Parse seed string into int or None."""
        return int(seed_str) if seed_str.isdigit() else None

    def is_enabled(self) -> bool:
        """Check if any failure injection is configured."""
        return self._rate > 0 or bool(self._ids)

    def should_skip_record(self, custom_id: str) -> bool:
        """
        Check if a batch record should be skipped (omitted from results).

        Used to test batch retry by creating "missing" records.

        Args:
            custom_id: The custom_id of the batch record

        Returns:
            True if record should be skipped (not included in results)
        """
        if not self.is_enabled():
            return False

        if custom_id in self._ids:
            logger.debug("[FAILURE INJECTION] Skipping record: %s (in ID list)", custom_id)
            return True

        if self._rate > 0 and self._rng.random() < self._rate:
            logger.debug("[FAILURE INJECTION] Skipping record: %s (random)", custom_id)
            return True

        return False

    def maybe_raise_error(self, error_class: type, message: str, **context) -> None:
        """
        Maybe raise an error to test retry logic.

        Used to test online client retry by simulating transient failures.

        Args:
            error_class: Exception class to raise (e.g., RateLimitError)
            message: Error message
            **context: Additional context for the error

        Raises:
            error_class: If failure should be injected
        """
        if not self.is_enabled():
            return

        # Only use rate-based injection for errors (IDs are for batch records)
        if self._rate > 0 and self._rng.random() < self._rate:
            logger.info("[FAILURE INJECTION] Raising %s", error_class.__name__)
            raise error_class(message, context={"injected": True, **context})

    def reset(self, seed: int | None = None) -> None:
        """
        Reset the RNG state. Useful for reproducible test sequences.

        Args:
            seed: New seed value, or None to use original seed
        """
        self._rng = random.Random(seed if seed is not None else self._seed)


# Module-level singleton
_injector = FailureInjector()


def should_skip_record(custom_id: str) -> bool:
    """
    Check if a batch record should be skipped.

    See FailureInjector.should_skip_record for details.
    """
    return _injector.should_skip_record(custom_id)


def maybe_raise_error(error_class: type, message: str, **context) -> None:
    """
    Maybe raise an error for retry testing.

    See FailureInjector.maybe_raise_error for details.
    """
    _injector.maybe_raise_error(error_class, message, **context)


def is_enabled() -> bool:
    """Check if failure injection is currently enabled."""
    return _injector.is_enabled()


def reset(seed: int | None = None) -> None:
    """Reset RNG state for reproducible tests."""
    _injector.reset(seed)
