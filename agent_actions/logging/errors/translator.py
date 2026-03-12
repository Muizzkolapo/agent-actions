"""Error translation facade using formatter strategies."""

import logging
from typing import Dict, Any, Optional, List

from agent_actions.utils.safe_format import extract_root_cause, safe_get_exception_message
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
    TemplateErrorFormatter,
    GenericErrorFormatter,
)
from .services import ErrorContextService

logger = logging.getLogger(__name__)


class ErrorTranslator:
    """Translates Python exceptions to user-friendly errors via a formatter chain."""

    def __init__(self):
        """Initialize formatter chain."""
        self.formatters: List[ErrorFormatter] = [
            YAMLSyntaxErrorFormatter(),  # Check YAML first (most specific)
            FunctionNotFoundFormatter(),  # Check function errors
            TemplateErrorFormatter(),  # Template variable errors
            ConfigurationErrorFormatter(),
            ModelErrorFormatter(),
            AuthenticationErrorFormatter(),
            FileErrorFormatter(),
            APIErrorFormatter(),
            GenericErrorFormatter(),  # Fallback - always matches
        ]

    def translate(self, exc: Exception, context: Optional[Dict[str, Any]] = None) -> UserError:
        """Convert any exception to a UserError with user-friendly message."""
        merged_context = ErrorContextService.merge_exception_context(exc, context)

        root_cause = extract_root_cause(exc)
        root_message = safe_get_exception_message(root_cause)

        logger.debug(
            "Translating error: %s -> %s: %s",
            type(exc).__name__,
            type(root_cause).__name__,
            root_message,
        )

        # Find first formatter that can handle this error.
        # GenericErrorFormatter (last in chain) always matches, so this loop
        # is guaranteed to return.
        for formatter in self.formatters:
            if formatter.can_handle(exc, root_cause, root_message):
                logger.debug("Using formatter: %s", type(formatter).__name__)
                return formatter.format(exc, root_cause, root_message, merged_context)

        # Unreachable: formatters is non-empty and GenericErrorFormatter always matches.
        raise AssertionError("No formatter matched — formatters chain is misconfigured")
