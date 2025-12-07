"""Error translation facade using formatter strategies."""

import logging
from typing import Dict, Any, Optional, List

from agent_actions.utilities.safe_format import (
    extract_root_cause,
    safe_get_exception_message
)
from .user_error import UserError
from .formatters import (
    ErrorFormatter,
    ConfigurationErrorFormatter,
    ModelErrorFormatter,
    AuthenticationErrorFormatter,
    FileErrorFormatter,
    APIErrorFormatter,
    YAMLSyntaxErrorFormatter,
    FunctionNotFoundFormatter,
    GenericErrorFormatter
)
from .services import ErrorContextService

logger = logging.getLogger(__name__)


class ErrorTranslator:
    """
    Translates Python exceptions to user-friendly errors.

    Uses Strategy Pattern with formatter chain. Each formatter
    handles a specific error category (Config, Model, Auth, etc.).
    """

    def __init__(self):
        """Initialize formatter chain."""
        self.formatters: List[ErrorFormatter] = [
            YAMLSyntaxErrorFormatter(),  # Check YAML first (most specific)
            FunctionNotFoundFormatter(),  # Check function errors
            ConfigurationErrorFormatter(),
            ModelErrorFormatter(),
            AuthenticationErrorFormatter(),
            FileErrorFormatter(),
            APIErrorFormatter(),
            GenericErrorFormatter(),  # Fallback - always matches
        ]

    def translate(self, exc: Exception, context: Optional[Dict[str, Any]] = None) -> UserError:
        """
        Main translation method - converts any exception to UserError.

        Args:
            exc: The exception to translate
            context: Optional context dict with keys like 'agent', 'file_path', etc.

        Returns:
            UserError with user-friendly message
        """
        # Merge exception context with passed context
        merged_context = ErrorContextService.merge_exception_context(exc, context)

        # Extract root cause for better error detection
        root_cause = extract_root_cause(exc)
        root_message = safe_get_exception_message(root_cause)

        logger.debug(
            f"Translating error: {type(exc).__name__} -> "
            f"{type(root_cause).__name__}: {root_message}"
        )

        # Find first formatter that can handle this error
        for formatter in self.formatters:
            if formatter.can_handle(exc, root_cause, root_message):
                logger.debug(f"Using formatter: {type(formatter).__name__}")
                return formatter.format(exc, root_cause, root_message, merged_context)

        # Should never reach here since GenericErrorFormatter always matches
        logger.warning("No formatter matched - using fallback")
        return self.formatters[-1].format(exc, root_cause, root_message, merged_context)
