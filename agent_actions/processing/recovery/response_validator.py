"""Shared ResponseValidator protocol and implementations for reprompt validation."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

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
    """Wraps a UDF registered via ``@reprompt_validation``."""

    def __init__(self, validation_name: str) -> None:
        from agent_actions.errors import ConfigurationError

        from .validation import get_validation_function

        self._name = validation_name
        try:
            self._func, self._feedback_message = get_validation_function(validation_name)
        except ValueError as e:
            raise ConfigurationError(
                f"Validation UDF '{validation_name}' not found: {e}",
                context={"validation_name": validation_name},
                cause=e,
            ) from e

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
    """Validates LLM output against an expected schema (not thread-safe)."""

    _import_warned: bool = False

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
        self._validator_available = self._check_import()

    @classmethod
    def _check_import(cls) -> bool:
        """Return True if schema validator module is importable (warns once on failure)."""
        try:
            from agent_actions.validation.schema_output_validator import (  # noqa: F401
                validate_output_against_schema,
            )

            return True
        except ImportError:
            if not cls._import_warned:
                logger.warning(
                    "Schema output validator not available; SchemaValidator will "
                    "pass all responses. Install the validation module to enable "
                    "schema checking."
                )
                cls._import_warned = True
            return False

    def validate(self, response: Any) -> bool:  # noqa: D401
        if not self._validator_available:
            return True

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

            errors = report.validation_errors or ["Schema mismatch detected"]
            self._last_feedback = "; ".join(errors)
            return False

        except (ValueError, KeyError) as e:
            self._last_feedback = f"Schema validation error: {e}"
            return False
        except Exception as e:
            logger.exception(
                "Unexpected error during schema validation for '%s': %s",
                self._action_name,
                e,
            )
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
    """Chains multiple validators, failing on the first failure (not thread-safe)."""

    def __init__(self, validators: list[ResponseValidator]) -> None:
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
    """Build the feedback string appended to the prompt on validation failure."""
    try:
        response_str = json.dumps(failed_response, indent=2)
    except Exception:
        response_str = str(failed_response)

    return f"""---
Your response failed validation: {feedback_message}

Your response: {response_str}

Please correct and respond again."""
