"""
User-friendly error formatting system.
"""

import logging
from typing import Dict, Any, Optional

from agent_actions.utils.safe_format import (
    safe_format_error,
    safe_get_exception_message,
    format_exception_chain_for_debug,
)
from .user_error import UserError
from .translator import ErrorTranslator

logger = logging.getLogger(__name__)


def format_user_error(exc: Exception, context: Optional[Dict[str, Any]] = None) -> str:
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
