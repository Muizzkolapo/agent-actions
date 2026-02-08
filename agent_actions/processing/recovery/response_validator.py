"""Shared ResponseValidator protocol and implementations.

Provides a unified interface for all validation in the reprompt loop --
UDF-based, schema-based, or composed chains. Both online (RepromptService)
and batch (BatchRetryService) paths use the same protocol.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ResponseValidator(Protocol):
    """Shared protocol for all validators -- UDF, schema, composed."""

    def validate(self, response: Any) -> bool:
        """Return True if *response* passes validation."""
        ...

    @property
    def feedback_message(self) -> str:
        """Human-readable explanation shown to the LLM on failure."""
        ...

    @property
    def name(self) -> str:
        """Short identifier for logging / metadata."""
        ...


# ---------------------------------------------------------------------------
# UDF validator
# ---------------------------------------------------------------------------


class UdfValidator:
    """Wraps a UDF registered via ``@reprompt_validation``.

    Parameters
    ----------
    validation_name:
        Key in the global ``_VALIDATION_REGISTRY``.  The function and
        feedback message are resolved at construction time via
        ``get_validation_function()``.
    """

    def __init__(self, validation_name: str) -> None:
        from .validation import get_validation_function

        self._name = validation_name
        self._func, self._feedback_message = get_validation_function(validation_name)

    def validate(self, response: Any) -> bool:  # noqa: D401
        return self._func(response)

    @property
    def feedback_message(self) -> str:
        return self._feedback_message

    @property
    def name(self) -> str:
        return self._name


# ---------------------------------------------------------------------------
# Schema validator
# ---------------------------------------------------------------------------


class SchemaValidator:
    """Validates LLM output against an expected schema.

    Parameters
    ----------
    schema:
        Schema dict (as stored in ``agent_config["schema"]``).
    action_name:
        Agent/action name for error reporting.
    strict_mode:
        When *True*, extra fields also cause failure.  Mirrors the
        existing ``strict_schema`` behaviour but channelled through
        the reprompt loop instead of raising immediately.
    """

    def __init__(
        self,
        schema: dict,
        action_name: str,
        strict_mode: bool = False,
    ) -> None:
        self._schema = schema
        self._action_name = action_name
        self._strict_mode = strict_mode
        self._last_feedback: str = ""

    def validate(self, response: Any) -> bool:  # noqa: D401
        try:
            from agent_actions.validation.schema_output_validator import (
                validate_output_against_schema,
            )

            report = validate_output_against_schema(
                response,
                self._schema,
                self._action_name,
                strict_mode=self._strict_mode,
            )

            if report.is_compliant:
                return True

            # Build a feedback string from the report
            errors = report.validation_errors or ["Schema mismatch detected"]
            self._last_feedback = "; ".join(errors)
            return False

        except ImportError:
            logger.debug("Schema output validator not available, treating as pass")
            return True
        except Exception as e:
            self._last_feedback = f"Schema validation error: {e}"
            return False

    @property
    def feedback_message(self) -> str:
        return self._last_feedback or "Response does not match expected schema"

    @property
    def name(self) -> str:
        return f"schema:{self._action_name}"


# ---------------------------------------------------------------------------
# Composed validator
# ---------------------------------------------------------------------------


class ComposedValidator:
    """Chains multiple validators; fails on the first failure.

    The LLM receives feedback for **one** issue at a time so it can
    focus on fixing that issue before the next validation fires.
    """

    def __init__(self, validators: List[ResponseValidator]) -> None:
        if not validators:
            raise ValueError("ComposedValidator requires at least one validator")
        self._validators = validators
        self._last_failed: ResponseValidator | None = None

    def validate(self, response: Any) -> bool:  # noqa: D401
        for v in self._validators:
            if not v.validate(response):
                self._last_failed = v
                return False
        self._last_failed = None
        return True

    @property
    def feedback_message(self) -> str:
        if self._last_failed is not None:
            return self._last_failed.feedback_message
        return ""

    @property
    def name(self) -> str:
        return "+".join(v.name for v in self._validators)


# ---------------------------------------------------------------------------
# Shared feedback formatter
# ---------------------------------------------------------------------------


def build_validation_feedback(failed_response: Any, feedback_message: str) -> str:
    """Build the feedback string appended to the prompt on validation failure.

    This is the **single source of truth** for feedback formatting, replacing
    both ``RepromptService._build_feedback_message`` and the standalone
    ``_build_reprompt_feedback`` in the batch retry module.
    """
    try:
        response_str = json.dumps(failed_response, indent=2)
    except Exception:
        response_str = str(failed_response)

    return f"""---
Your response failed validation: {feedback_message}

Your response: {response_str}

Please correct and respond again."""
