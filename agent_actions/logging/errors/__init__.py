"""
User-friendly error formatting system.
"""

import logging
from typing import Any

from agent_actions.utils.safe_format import (
    format_exception_chain_for_debug,
    safe_format_error,
    safe_get_exception_message,
)

from .translator import ErrorTranslator
from .user_error import UserError

logger = logging.getLogger(__name__)


def format_user_error(exc: Exception, context: dict[str, Any] | None = None) -> str:
    """Convert any exception to a user-friendly error message string."""
    logger.debug(
        "Formatting user error: %s",
        safe_get_exception_message(exc),
        extra={"context": context or {}},
    )
    logger.debug("Error occurred during operation", exc_info=exc, extra={"context": context or {}})
    logger.debug("Exception chain details:\n%s", format_exception_chain_for_debug(exc))

    try:
        translator = ErrorTranslator()
        user_error = translator.translate(exc, context)
        return user_error.format_for_cli()
    except Exception as format_error:
        # Catch all exceptions to prevent error formatting from breaking error reporting
        logger.error("Error formatting failed", exc_info=format_error)
        return safe_format_error(exc)


__all__ = ["UserError", "ErrorTranslator", "format_user_error"]
