"""
Interceptor that validates responses using user-defined functions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from agent_actions.errors import (
    AgentActionsException,
    ConfigurationError,
    ValidationError,
)
from agent_actions.response_processing.base import (
    InterceptorResult,
    ResponseInterceptor,
)
from agent_actions.utilities.udf_management.tooling import (
    _split_udf_name,
    load_user_defined_function,
)

logger = logging.getLogger(__name__)


class ValidationInterceptor(ResponseInterceptor):
    """Interceptor that validates responses against configured criteria."""

    def __init__(self) -> None:
        self.validator_function: str | None = None
        self.validator_args: Dict[str, Any] = {}
        self.on_failure: str = "retry"
        self.prompt_debug: bool = False

    def configure(self, config: Dict) -> None:
        self.prompt_debug = config.get("prompt_debug", False)
        logger.debug(
            "Validation interceptor configuration started",
            extra={
                "operation": "validation_configure",
                "config_keys": list(config.keys()),
                "prompt_debug": self.prompt_debug,
            },
        )

        self.validator_function = config.get("validator_function")
        self.validator_args = config.get("validator_args", {})
        self.on_failure = config.get("on_failure", "retry")

        logger.debug(
            "Validation interceptor configured",
            extra={
                "operation": "validation_configured",
                "validator_function": self.validator_function,
                "validator_args": self.validator_args,
                "on_failure": self.on_failure,
            },
        )

        if not self.validator_function:
            raise ConfigurationError(
                "validator_function is required",
                context={"interceptor_type": "validation", "config_keys": list(config.keys())},
            )

    def intercept(self, response: Any, context: Dict) -> InterceptorResult:
        logger.debug(
            "Validation interceptor invoked",
            extra={
                "operation": "validation_intercept_start",
                "response_type": type(response).__name__,
                "attempt": context.get("attempt", "unknown"),
                "has_validator": bool(self.validator_function),
            },
        )

        if not self.validator_function:
            logger.debug(
                "No validator function configured, continuing",
                extra={"operation": "validation_no_validator"},
            )
            return InterceptorResult(continue_processing=True)

        logger.debug(
            "Running validator function",
            extra={
                "operation": "validation_execute",
                "validator_function": self.validator_function,
                "validator_args": self.validator_args,
            },
        )

        try:
            module_name, func_name = _split_udf_name(self.validator_function)
            validator_func = load_user_defined_function(module_name, func_name)
            merged_kwargs = {**self.validator_args, **context}
            success, error_message = validator_func(response, **merged_kwargs)
        except (ConfigurationError, AgentActionsException, ValueError, TypeError) as e:
            logger.exception(
                "Error loading or executing validator function",
                extra={
                    "operation": "validation_error",
                    "validator_function": self.validator_function,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            success, error_message = (False, f"Validator function error: {str(e)}")

        logger.info(
            "Validation result",
            extra={
                "operation": "validation_result",
                "success": success,
                "error_message": error_message,
                "validator_function": self.validator_function,
            },
        )

        if success:
            logger.debug(
                "Validation passed, continuing with response",
                extra={"operation": "validation_passed"},
            )
            return InterceptorResult(continue_processing=True)

        if self.on_failure == "retry":
            logger.warning(
                "Validation failed, setting up retry",
                extra={
                    "operation": "validation_failed_retry",
                    "error_message": error_message,
                    "validator_function": self.validator_function,
                },
            )
            return InterceptorResult(
                continue_processing=False,
                retry_context={
                    "validation_error": error_message,
                    "validator_function": self.validator_function,
                    "validator_args": self.validator_args,
                    "failed_response": response,
                },
            )

        if self.on_failure == "fail":
            logger.error(
                "Validation failed, raising error",
                extra={
                    "operation": "validation_failed_error",
                    "error_message": error_message,
                    "validator_function": self.validator_function,
                },
            )
            raise ValidationError(
                "Validation failed",
                context={
                    "validator_function": self.validator_function,
                    "error_message": error_message,
                    "validator_args": self.validator_args,
                },
            )

        logger.warning(
            "Validation failed, continuing with warning",
            extra={
                "operation": "validation_failed_continue",
                "error_message": error_message,
                "validator_function": self.validator_function,
            },
        )
        return InterceptorResult(
            continue_processing=True, metadata={"validation_warning": error_message}
        )
