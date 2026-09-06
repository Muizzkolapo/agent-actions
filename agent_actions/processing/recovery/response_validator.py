"""Schema conformance check for a produced record.

Used by the expectation loop's structural gate, which turns a record the schema
rejects into a failing outcome the repair prompt can act on.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Strategy callable: (failed_response, feedback_message) -> extra prompt text
FeedbackStrategy = Callable[[Any, str], str]


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
        self._validator_module = None
        if self._validator_available:
            from agent_actions.validation import schema_output_validator

            self._validator_module = schema_output_validator

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
        if not self._validator_available or self._validator_module is None:
            return True

        try:
            report = self._validator_module.validate_output_against_schema(
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
