"""External service and vendor API errors."""
# Too-many-arguments: Legacy compatibility for VendorAPIError requires all parameters
# Unnecessary-pass: Simple exception classes inherit all behavior from parent

from typing import Optional, Dict, Any
from agent_actions.errors.base import AgentActionsError


class ExternalServiceError(AgentActionsError):
    """Base exception for external service interactions."""

    pass


class VendorAPIError(ExternalServiceError):
    """Raised when an error occurs during a call to a vendor's API."""

    def __init__(
        self,
        message_or_vendor: Optional[str] = None,
        endpoint: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None,
        **kwargs,
    ):
        """
        Initialize VendorAPIError.

        Supports two signatures:
        1. VendorAPIError(message, context=..., cause=...)
        2. VendorAPIError(vendor="...", endpoint="...", context=...)

        Args:
            message_or_vendor: Error message OR vendor name (if positional)
            endpoint: API endpoint
            context: Additional error context
            cause: Underlying exception
            **kwargs: Support for 'vendor' keyword argument
        """
        vendor = kwargs.pop("vendor", None)

        if vendor:
            # Case: vendor passed as kwarg
            message = f"Error calling {vendor} API endpoint {endpoint}"
            if context is None:
                context = {}
            context["vendor"] = vendor
            if endpoint:
                context["endpoint"] = endpoint
        elif endpoint is not None and message_or_vendor:
            # Case: vendor passed as positional first arg
            vendor = message_or_vendor
            message = f"Error calling {vendor} API endpoint {endpoint}"
            if context is None:
                context = {}
            context["vendor"] = vendor
            context["endpoint"] = endpoint
        else:
            # Case: message passed as first arg
            message = message_or_vendor or "Unknown Vendor API Error"

        super().__init__(message, context=context, cause=cause)


class OpenAIError(VendorAPIError):
    """Specific error for OpenAI API failures."""

    pass


class AnthropicError(VendorAPIError):
    """Specific error for Anthropic API failures."""

    pass


class GeminiError(VendorAPIError):
    """Specific error for Gemini API failures."""

    pass


class NetworkError(ExternalServiceError):
    """Raised when network-related errors occur (timeout, connection, etc)."""

    pass


class RateLimitError(VendorAPIError):
    """Raised when API rate limits are exceeded."""

    pass
