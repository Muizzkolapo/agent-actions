"""Wave 9 Group H regression tests — Error class constructor P1 fixes."""

from agent_actions.errors.base import AgentActionsError
from agent_actions.errors.configuration import ConfigValidationError
from agent_actions.errors.external_services import VendorAPIError

# ---------------------------------------------------------------------------
# H-1  ·  VendorAPIError — endpoint=None no longer interpolated as "None"
# ---------------------------------------------------------------------------


class TestVendorAPIErrorEndpointGuard:
    """H-1 — endpoint=None becomes "<unknown>" in the message."""

    def test_none_endpoint_becomes_unknown(self):
        err = VendorAPIError(vendor="openai", endpoint=None)
        assert "<unknown>" in str(err), "endpoint=None must produce '<unknown>' in message"
        assert "None" not in str(err), "literal 'None' must not appear in message"

    def test_explicit_endpoint_used_verbatim(self):
        err = VendorAPIError(vendor="openai", endpoint="/v1/batches")
        assert "/v1/batches" in str(err)

    def test_no_vendor_falls_back_to_message(self):
        err = VendorAPIError(message="Custom error")
        assert "Custom error" in str(err)


# ---------------------------------------------------------------------------
# H-2  ·  ConfigValidationError — effective_key falls back to "<no key>"
# ---------------------------------------------------------------------------


class TestConfigValidationErrorNoKeyFallback:
    """H-2 — config_key=None, message=None produces '<no key>' not 'None'."""

    def test_both_none_produces_no_key_sentinel(self):
        err = ConfigValidationError(reason="something went wrong")
        assert "<no key>" in str(err), (
            "effective_key must be '<no key>' when both config_key and message are None"
        )
        assert "None" not in str(err), "literal 'None' must not appear in message"

    def test_config_key_takes_priority(self):
        err = ConfigValidationError(reason="bad value", config_key="model_vendor")
        assert "model_vendor" in str(err)

    def test_message_fallback_when_no_config_key(self):
        err = ConfigValidationError(message="fallback_name", reason="missing")
        assert "fallback_name" in str(err)


# ---------------------------------------------------------------------------
# H-3  ·  AgentActionsError — context dict is defensively copied
# ---------------------------------------------------------------------------


class TestAgentActionsErrorDefensiveCopy:
    """H-3 — mutating the context dict after construction doesn't affect the error."""

    def test_context_is_not_same_object(self):
        ctx = {"key": "value"}
        err = AgentActionsError("test", context=ctx)
        assert err.context is not ctx, "context must be a copy, not the same object"

    def test_none_context_produces_empty_dict(self):
        err = AgentActionsError("test", context=None)
        assert err.context == {}

    def test_non_dict_context_stored_as_is_for_backward_compat(self):
        """Non-dict context (e.g., string) is preserved — backward compat for test_exceptions.py."""
        err = AgentActionsError("test", context="string context")  # type: ignore[arg-type]
        assert err.context == "string context"

    def test_endpoint_always_in_vendor_api_error_context(self):
        """After H-1 fix, endpoint is always added to ctx (no dead 'if endpoint:' branch)."""
        err = VendorAPIError(vendor="openai", endpoint=None)
        assert err.context.get("endpoint") == "<unknown>", (
            "endpoint must be in context even when originally None"
        )
