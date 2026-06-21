"""Tests for ConfigurationErrorFormatter — specifically the UDFLoadError defer.

UDFLoadError extends ConfigurationError, so the configuration formatter's name-
based ``"Config" in exc_names`` match would otherwise claim UDF load errors and
strip the module/file/install-hint context that UDFLoadErrorFormatter renders.
The formatter has an explicit isinstance guard to defer; this file locks that
behavior in so a future refactor can't silently regress.
"""

import pytest

from agent_actions.errors import ConfigValidationError, UDFLoadError
from agent_actions.logging.errors.formatters.configuration import (
    ConfigurationErrorFormatter,
)


@pytest.fixture
def formatter():
    return ConfigurationErrorFormatter()


class TestUDFLoadErrorDefer:
    """ConfigurationErrorFormatter must never claim UDFLoadError, regardless of
    chain ordering."""

    def test_defers_when_udf_load_error_is_outer_exception(self, formatter):
        exc = UDFLoadError(module="proj.bad", file="/proj/bad.py", error="boom")
        assert not formatter.can_handle(exc, exc, str(exc))

    def test_defers_when_udf_load_error_is_root_cause(self, formatter):
        root = UDFLoadError(module="proj.bad", file="/proj/bad.py", error="boom")
        wrapped = RuntimeError("workflow failed")
        wrapped.__cause__ = root
        assert not formatter.can_handle(wrapped, root, str(root))

    def test_defers_for_discovery_sentinel_too(self, formatter):
        exc = UDFLoadError(
            module=UDFLoadError.DISCOVERY_SENTINEL,
            file="/no/such/dir",
            error="User code directory not found",
        )
        assert not formatter.can_handle(exc, exc, str(exc))

    def test_defers_for_udf_load_error_subclass(self, formatter):
        class CustomUDFLoadError(UDFLoadError):
            pass

        exc = CustomUDFLoadError(module="proj.bad", file="/x.py", error="boom")
        assert not formatter.can_handle(exc, exc, str(exc))


class TestStillClaimsOtherConfigurationErrors:
    """Sanity: the defer must not regress the formatter's normal claims."""

    def test_claims_config_validation_error(self, formatter):
        exc = ConfigValidationError(reason="bad value", config_key="some.key")
        assert formatter.can_handle(exc, exc, str(exc))

    def test_claims_message_with_yaml_substring(self, formatter):
        exc = ValueError("invalid yaml in config")
        assert formatter.can_handle(exc, exc, str(exc))
