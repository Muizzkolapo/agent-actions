"""Shared mock validators and utility helpers for doc audit tests."""

from __future__ import annotations

from typing import Any

from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.recovery.validation import (
    _REGISTRY_LOCK,
    _VALIDATION_REGISTRY,
)
from agent_actions.processing.types import RecoveryMetadata

# _REGISTRY_LOCK and _VALIDATION_REGISTRY are private internals used only for
# test isolation (clearing the global UDF registry between tests).  If the
# validation module is refactored, these imports will need updating.  A public
# clear_registry() on the validation module would be a better long-term solution.

# ---------------------------------------------------------------------------
# Mock validators (implement the ResponseValidator protocol)
# ---------------------------------------------------------------------------


class AlwaysPass:
    def validate(self, response: Any) -> bool:
        return True

    @property
    def feedback_message(self) -> str:
        return ""

    @property
    def name(self) -> str:
        return "always_pass"


class AlwaysFail:
    def __init__(self, feedback: str = "always wrong") -> None:
        self._feedback = feedback

    def validate(self, response: Any) -> bool:
        return False

    @property
    def feedback_message(self) -> str:
        return self._feedback

    @property
    def name(self) -> str:
        return "always_fail"


class SimpleValidator:
    """Pass on the Nth call (1-indexed)."""

    def __init__(self, *, pass_on_attempt: int = 1, feedback: str = "fix it") -> None:
        self._pass_on = pass_on_attempt
        self._calls = 0
        self._feedback = feedback

    def validate(self, response: Any) -> bool:
        self._calls += 1
        return self._calls >= self._pass_on

    @property
    def feedback_message(self) -> str:
        return self._feedback

    @property
    def name(self) -> str:
        return "simple_test_validator"


class RaisingValidator:
    """Validator whose validate() raises."""

    def validate(self, response: Any) -> bool:
        raise ValueError("boom")

    @property
    def feedback_message(self) -> str:
        return ""

    @property
    def name(self) -> str:
        return "raising"


# ---------------------------------------------------------------------------
# UDF registry helpers
# ---------------------------------------------------------------------------


def clear_registry() -> None:
    """Remove all registered UDFs (test isolation)."""
    with _REGISTRY_LOCK:
        _VALIDATION_REGISTRY.clear()


def register_test_udf(name: str, *, passes: bool = True, feedback: str = "bad") -> None:
    """Register a trivial UDF for testing."""
    with _REGISTRY_LOCK:
        _VALIDATION_REGISTRY[name] = (lambda r: passes, feedback)


# ---------------------------------------------------------------------------
# BatchResult factory
# ---------------------------------------------------------------------------


def br(
    cid: str,
    content: Any,
    success: bool = True,
    recovery: RecoveryMetadata | None = None,
) -> BatchResult:
    """Shorthand to build a BatchResult with optional recovery metadata."""
    r = BatchResult(custom_id=cid, content=content, success=success)
    r.recovery_metadata = recovery
    return r
