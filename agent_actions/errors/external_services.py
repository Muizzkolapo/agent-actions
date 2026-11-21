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


class QuotaExceededError(VendorAPIError):
    """Raised when the provider says the account's quota, credit or balance is used up.

    Not retriable: no wait clears it, as a wait clears a rate limit.
    """

    @property
    def provider_message(self) -> str:
        """The provider's own text for the stop."""
        return str(self.context.get("provider_message") or self)


class ProviderQuotaStop(BaseException):
    """Ends the run when a provider's quota is used up, as an interrupt ends it.

    Not an ``Exception``: the handlers that fail a record, a file or an action on an
    error must not see it, so a record without an answer keeps no disposition and the
    next run resumes it.
    """

    def __init__(self, provider: str, provider_message: str):
        self.provider = provider
        self.provider_message = provider_message
        super().__init__(
            f"Provider quota or billing stop ({provider}): {provider_message.rstrip('. ')}. "
            "Add credits, then run again to resume."
        )


class ResponseTruncatedError(VendorAPIError):
    """Raised when the output budget ran out before the model wrote any answer.

    Retriable: a model that thinks first spends a different share of the budget on
    each attempt.
    """

    pass


class PromptTooLargeError(VendorAPIError):
    """Raised when the assembled prompt exceeds the model's context window."""

    pass
