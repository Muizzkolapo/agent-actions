"""
User-friendly error formatting system.

This module converts internal Python exceptions into clear, actionable
error messages for config authors (similar to dbt/Terraform tools).
Users should never see Python stack traces or internal implementation details.
"""

import logging
from typing import Dict, Any, Optional

from agent_actions.utilities.safe_format import (
    safe_format_error,
    format_exception_chain_for_debug
)
from .user_error import UserError
from .error_translator import ErrorTranslator

logger = logging.getLogger(__name__)


def format_user_error(exc: Exception, context: Optional[Dict[str, Any]] = None) -> str:
    """
    Convert any exception to a user-friendly error message.

    This is the main entry point for error formatting. It logs the full
    exception for debugging while returning a clean message for users.

    Args:
        exc: The exception to format
        context: Optional context dict with keys like 'agent', 'file_path', etc.

    Returns:
        User-friendly error message string
    """
    # ALWAYS log full error for debugging with complete exception chain
    logger.error(
        "Error occurred during operation",
        exc_info=exc,
        extra={'context': context or {}}
    )
    # Log the detailed exception chain for debugging (not shown to users)
    logger.debug(f"Exception chain details:\n{format_exception_chain_for_debug(exc)}")

    try:
        translator = ErrorTranslator()
        user_error = translator.translate(exc, context)
        return user_error.format_for_cli()
    except Exception as format_error:
        # If formatting fails, log and use safe fallback
        logger.error("Error formatting failed", exc_info=format_error)
        return safe_format_error(exc)


__all__ = ['UserError', 'ErrorTranslator', 'format_user_error']
