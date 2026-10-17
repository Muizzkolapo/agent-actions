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


class TestAPreflightRefusalKeepsItsOwnWords:
    """A refusal that mentions schema validation must not become a generic YAML error (1491)."""

    def test_the_refusal_message_and_hint_are_shown(self):
        from agent_actions.errors.preflight import PreFlightValidationError
        from agent_actions.logging.errors.translator import ErrorTranslator

        exc = PreFlightValidationError(
            "producer: output schema requires 'items'; runtime schema validation fails it",
            hint="Make the field optional",
        )
        error = ErrorTranslator().translate(exc, {"agent": "w"})

        assert "output schema requires 'items'" in error.details
        assert error.fix == "Make the field optional"
        assert "YAML" not in error.fix


class TestAnErrorThatMentionsSchemaValidationKeepsItsOwnWords:
    """Only an error with nothing better to say gets the generic schema text (1510)."""

    def test_a_configuration_error_shows_its_message(self):
        from agent_actions.errors import ConfigurationError
        from agent_actions.logging.errors.translator import ErrorTranslator

        exc = ConfigurationError(
            "Seed 'prices': row 3 failed schema validation: 'amount' must be a number"
        )
        error = ErrorTranslator().translate(exc, {"agent": "w"})

        assert "row 3 failed schema validation: 'amount' must be a number" in error.details
        assert "The configuration format is invalid" not in error.details

    def test_a_hint_the_error_carries_is_the_fix(self):
        from agent_actions.errors import ConfigurationError
        from agent_actions.logging.errors.translator import ErrorTranslator

        exc = ConfigurationError(
            "Seed 'prices': row 3 failed schema validation",
            context={"hint": "Fix row 3 of seed_data/prices.json"},
        )
        error = ErrorTranslator().translate(exc, {"agent": "w"})

        assert error.fix == "Fix row 3 of seed_data/prices.json"

    def test_a_wrapped_error_shows_its_root_message(self):
        from agent_actions.errors import AgentActionsError
        from agent_actions.logging.errors.translator import ErrorTranslator

        root = ValueError("payload failed schema validation: 'id' is required")
        exc = AgentActionsError("Error executing UDF 'load'", cause=root)
        exc.__cause__ = root
        error = ErrorTranslator().translate(exc, {"agent": "w"})

        assert "payload failed schema validation: 'id' is required" in error.details

    def test_a_schema_validation_error_still_shows_its_report(self):
        from agent_actions.errors import SchemaValidationError
        from agent_actions.logging.errors.translator import ErrorTranslator

        exc = SchemaValidationError(
            "Output schema validation failed for UDF 'produce' at root: 'items' is required",
            missing_fields=["items"],
        )
        error = ErrorTranslator().translate(exc, {"agent": "w"})

        assert error.title == "Schema validation failed"
        assert "'items' is required" in error.details
        assert "items" in error.details
