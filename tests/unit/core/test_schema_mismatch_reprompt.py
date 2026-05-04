"""Integration tests for reprompt.on_schema_mismatch.

Covers:
- _resolve_schema_mismatch_mode returns correct mode from reprompt config
- _validate_llm_output_schema skips when mode is "reprompt"
- _validate_llm_output_schema still raises when mode is "reject"
- _validate_llm_output_schema reprompt fallback logs warning
- Factory builds SchemaValidator when mode is "reprompt"
- Factory composes UDF + schema when both configured
- Factory raises on unregistered UDF name
- RepromptService with SchemaValidator triggers reprompt on schema failure
- create_reprompt_service_from_config with validator + no validation key
"""

from unittest.mock import Mock, patch

import pytest

from agent_actions.processing.helpers import (
    _resolve_schema_mismatch_mode,
    _validate_llm_output_schema,
)
from agent_actions.processing.invocation.factory import InvocationStrategyFactory
from agent_actions.processing.recovery.reprompt import (
    RepromptService,
    create_reprompt_service_from_config,
)
from agent_actions.processing.recovery.response_validator import (
    ComposedValidator,
    SchemaValidator,
    UdfValidator,
)
from agent_actions.processing.recovery.validation import (
    _VALIDATION_REGISTRY,
    reprompt_validation,
)

# ---------------------------------------------------------------------------
# _resolve_schema_mismatch_mode
# ---------------------------------------------------------------------------


class TestResolveSchemaMode:
    """Tests for _resolve_schema_mismatch_mode reading from reprompt config."""

    def test_default_is_warn_when_no_reprompt(self):
        assert _resolve_schema_mismatch_mode({}) == "warn"

    def test_explicit_reprompt(self):
        config = {"reprompt": {"on_schema_mismatch": "reprompt"}}
        assert _resolve_schema_mismatch_mode(config) == "reprompt"

    def test_explicit_reject(self):
        config = {"reprompt": {"on_schema_mismatch": "reject"}}
        assert _resolve_schema_mismatch_mode(config) == "reject"

    def test_reprompt_dict_without_on_schema_mismatch_defaults_to_warn(self):
        """Reprompt config without on_schema_mismatch falls through to warn."""
        config = {"reprompt": {"validation": "check_fn"}}
        assert _resolve_schema_mismatch_mode(config) == "warn"


# ---------------------------------------------------------------------------
# Shared test helper
# ---------------------------------------------------------------------------


def _make_schema_config(on_schema_mismatch=None):
    """Build a minimal config with a two-field schema and optional mismatch mode."""
    config = {
        "schema": {
            "fields": [
                {"name": "title", "type": "string", "required": True},
                {"name": "score", "type": "number", "required": True},
            ]
        },
    }
    if on_schema_mismatch:
        config["reprompt"] = {"on_schema_mismatch": on_schema_mismatch}
    return config


# ---------------------------------------------------------------------------
# _validate_llm_output_schema skip behavior
# ---------------------------------------------------------------------------


class TestValidateSchemaSkip:
    """Tests for _validate_llm_output_schema skip/fallback behavior."""

    def test_reprompt_mode_skips_when_flag_set(self):
        """With skip_schema_validation=True, returns response unchanged."""
        config = _make_schema_config(on_schema_mismatch="reprompt")
        response = {"wrong_field": "value"}
        result = _validate_llm_output_schema(
            response, config, "test_action", skip_schema_validation=True
        )
        assert result == response  # skipped, no exception

    def test_reprompt_mode_falls_back_to_warn_without_flag(self):
        """Without skip_schema_validation, reprompt mode falls back to warn."""
        config = _make_schema_config(on_schema_mismatch="reprompt")
        response = {"wrong_field": "value"}
        # Should NOT skip -- falls back to warn (returns response, logs warning)
        result = _validate_llm_output_schema(response, config, "test_action")
        assert result == response  # warn mode returns response, no exception

    def test_reject_mode_raises(self):
        """on_schema_mismatch: reject still raises."""
        from agent_actions.errors import SchemaValidationError

        config = _make_schema_config(on_schema_mismatch="reject")
        response = {"wrong_field": "value"}
        with pytest.raises(SchemaValidationError):
            _validate_llm_output_schema(response, config, "test_action")

    def test_no_schema_returns_immediately(self):
        """No schema configured -- skip entirely."""
        result = _validate_llm_output_schema({"data": 1}, {}, "test_action")
        assert result == {"data": 1}


# ---------------------------------------------------------------------------
# Factory _build_validator
# ---------------------------------------------------------------------------


class TestFactoryBuildValidator:
    """Tests for InvocationStrategyFactory._build_validator."""

    def setup_method(self):
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Must be positive")
        def check_positive(response: dict) -> bool:
            return response.get("value", 0) > 0

    def test_no_config_returns_none(self):
        result = InvocationStrategyFactory._build_validator({})
        assert result is None

    def test_udf_only(self):
        config = {"reprompt": {"validation": "check_positive"}}
        result = InvocationStrategyFactory._build_validator(config)
        assert isinstance(result, UdfValidator)
        assert result.name == "check_positive"

    def test_schema_reprompt_only(self):
        config = {
            "schema": {"fields": [{"name": "x", "type": "string", "required": True}]},
            "reprompt": {"on_schema_mismatch": "reprompt"},
            "name": "my_action",
        }
        result = InvocationStrategyFactory._build_validator(config)
        assert isinstance(result, SchemaValidator)
        assert result.name == "schema:my_action"

    def test_schema_without_reprompt_mismatch_not_included(self):
        """Schema without on_schema_mismatch in reprompt should NOT produce a validator."""
        config = {
            "schema": {"fields": [{"name": "x", "type": "string", "required": True}]},
            "name": "my_action",
        }
        result = InvocationStrategyFactory._build_validator(config)
        assert result is None

    def test_both_udf_and_schema(self):
        config = {
            "reprompt": {
                "validation": "check_positive",
                "on_schema_mismatch": "reprompt",
            },
            "schema": {"fields": [{"name": "x", "type": "string", "required": True}]},
            "name": "my_action",
        }
        result = InvocationStrategyFactory._build_validator(config)
        assert isinstance(result, ComposedValidator)
        assert "check_positive" in result.name
        assert "schema:my_action" in result.name


# ---------------------------------------------------------------------------
# End-to-end: SchemaValidator in RepromptService
# ---------------------------------------------------------------------------


class TestSchemaRepromptEndToEnd:
    """RepromptService with SchemaValidator triggers reprompt on schema failure."""

    def _make_schema(self):
        return {
            "fields": [
                {"name": "title", "type": "string", "required": True},
                {"name": "score", "type": "number", "required": True},
            ]
        }

    def test_schema_fail_then_pass(self):
        """Schema failure triggers reprompt; second attempt passes."""
        validator = SchemaValidator(self._make_schema(), "test_action")
        service = RepromptService(validator=validator, max_attempts=3)

        llm_operation = Mock(
            side_effect=[
                ({"wrong": "data"}, True),  # schema fail
                ({"title": "ok", "score": 5}, True),  # schema pass
            ]
        )

        result = service.execute(
            llm_operation=llm_operation,
            original_prompt="Generate data",
            context="test",
        )

        assert result.passed is True
        assert result.attempts == 2
        assert llm_operation.call_count == 2

    def test_schema_always_fails_exhausted(self):
        """Schema always fails → exhausted."""
        validator = SchemaValidator(self._make_schema(), "test_action")
        service = RepromptService(validator=validator, max_attempts=2, on_exhausted="return_last")

        llm_operation = Mock(
            side_effect=[
                ({"wrong": "data"}, True),
                ({"still_wrong": "data"}, True),
            ]
        )

        result = service.execute(
            llm_operation=llm_operation,
            original_prompt="Generate data",
            context="test",
        )

        assert result.passed is False
        assert result.exhausted is True
        assert result.attempts == 2

    def test_composed_validator_name_in_metadata(self):
        """Composed validator name should appear in result.validation_name."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Must be positive")
        def check_positive(response: dict) -> bool:
            return response.get("value", 0) > 0

        composed = ComposedValidator(
            [
                UdfValidator("check_positive"),
                SchemaValidator(self._make_schema(), "my_action"),
            ]
        )
        service = RepromptService(validator=composed, max_attempts=1, on_exhausted="return_last")

        llm_operation = Mock(return_value=({"value": -1}, True))
        result = service.execute(
            llm_operation=llm_operation,
            original_prompt="test",
            context="test",
        )

        # validation_name should reflect the composed validator, not just UDF
        assert "check_positive" in result.validation_name
        assert "schema:my_action" in result.validation_name


# ---------------------------------------------------------------------------
# HIGH gap 1: create_reprompt_service_from_config with validator, no validation key
# ---------------------------------------------------------------------------


class TestCreateRepromptServiceWithValidator:
    """Test create_reprompt_service_from_config when validator is provided."""

    def test_validator_with_max_attempts_no_validation_key(self):
        """Validator + reprompt_config with max_attempts but no 'validation' key."""
        schema = {"fields": [{"name": "x", "type": "string", "required": True}]}
        validator = SchemaValidator(schema, "test_action")
        reprompt_config = {"max_attempts": 3, "on_exhausted": "return_last"}

        service = create_reprompt_service_from_config(reprompt_config, validator=validator)

        assert service is not None
        assert service.max_attempts == 3
        assert service.on_exhausted == "return_last"
        assert service.validation_name == "schema:test_action"

    def test_validator_without_reprompt_config_uses_defaults(self):
        """Validator provided but reprompt_config is None → service with defaults."""
        schema = {"fields": [{"name": "x", "type": "string", "required": True}]}
        validator = SchemaValidator(schema, "test_action")

        service = create_reprompt_service_from_config(None, validator=validator)

        assert service is not None
        assert service.max_attempts == 2  # default
        assert service.validation_name == "schema:test_action"

    def test_no_validator_no_validation_key_raises(self):
        """No validator and no 'validation' key → ValueError."""
        reprompt_config = {"max_attempts": 3}
        with pytest.raises(ValueError, match="missing required 'validation' field"):
            create_reprompt_service_from_config(reprompt_config)


# ---------------------------------------------------------------------------
# HIGH gap 2: reprompt fallback logs a warning
# ---------------------------------------------------------------------------


class TestRepromptFallbackWarning:
    """Test that reprompt mode without skip_schema_validation logs a warning."""

    @patch("agent_actions.processing.helpers.logger")
    def test_reprompt_fallback_logs_warning(self, mock_logger):
        """Reprompt mode without flag falls back to warn and logs."""
        config = _make_schema_config(on_schema_mismatch="reprompt")
        response = {"wrong_field": "value"}

        result = _validate_llm_output_schema(response, config, "test_action")

        assert result == response  # returned, not raised
        mock_logger.warning.assert_called()
        warning_args = str(mock_logger.warning.call_args)
        assert "Schema validation warning" in warning_args


# ---------------------------------------------------------------------------
# HIGH gap 3: _build_validator with unregistered UDF name
# ---------------------------------------------------------------------------


class TestBuildValidatorUnregisteredUdf:
    """Test _build_validator when UDF name is not in registry."""

    def setup_method(self):
        _VALIDATION_REGISTRY.clear()

    def test_unregistered_udf_raises_valueerror(self):
        """_build_validator with a UDF name not in the registry raises ConfigurationError."""
        from agent_actions.errors import ConfigurationError

        config = {"reprompt": {"validation": "nonexistent_udf"}}
        with pytest.raises(ConfigurationError, match="not found"):
            InvocationStrategyFactory._build_validator(config)
