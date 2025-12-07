"""External service and vendor API errors."""

from agent_actions.errors.base import AgentActionsError


class ExternalServiceError(AgentActionsError):
    """Base exception for external service interactions."""
    pass


class VendorAPIError(ExternalServiceError):
    """Raised when an error occurs during a call to a vendor's API."""
    pass


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
