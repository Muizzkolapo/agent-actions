"""External service and vendor API errors."""

from typing import Any

from agent_actions.errors.base import AgentActionsError


class ExternalServiceError(AgentActionsError):
    """Base exception for external service interactions."""

    pass


class VendorAPIError(ExternalServiceError):
    """Raised when an error occurs during a call to a vendor's API."""

    def __init__(
        self,
        message: str | None = None,
        *,
        vendor: str | None = None,
        endpoint: str | None = None,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        ctx = dict(context) if context else {}

        if vendor:
            endpoint = endpoint or "<unknown>"
            msg = f"Error calling {vendor} API endpoint {endpoint}"
            ctx["vendor"] = vendor
            ctx["endpoint"] = endpoint
        else:
            msg = message or "Unknown Vendor API Error"

        super().__init__(msg, context=ctx, cause=cause)


class AnthropicError(VendorAPIError):
    """Specific error for Anthropic API failures."""

    pass


class NetworkError(ExternalServiceError):
    """Raised when network-related errors occur (timeout, connection, etc)."""

    pass


class RateLimitError(VendorAPIError):
    """Raised when API rate limits are exceeded."""

    pass
