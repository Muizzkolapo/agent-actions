"""Tests for consolidated guard configuration with behavior control.

Following TDD approach - these tests define the expected API and behavior.
"""

import pytest

from agent_actions.errors import ConfigValidationError, ValidationError
from agent_actions.guards import (
    GuardBehavior,
    GuardConfig,
    parse_guard_config,
)


class TestGuardConfig:
    """Test the new GuardConfig class for consolidated guard behavior."""

    def test_guard_config_with_skip_behavior(self):
        """Test GuardConfig with skip behavior (passthrough)."""
        config = GuardConfig(
            condition="udf:validators.should_extract_facts", on_false=GuardBehavior.SKIP
        )
        assert config.condition == "udf:validators.should_extract_facts"
        assert config.on_false == GuardBehavior.SKIP
        assert config.is_udf_condition() is True
        assert config.is_sql_condition() is False

    def test_guard_config_with_filter_behavior(self):
        """Test GuardConfig with filter behavior (remove records)."""
        config = GuardConfig(condition='questionable != "Low Value"', on_false=GuardBehavior.FILTER)
        assert config.condition == 'questionable != "Low Value"'
        assert config.on_false == GuardBehavior.FILTER
        assert config.is_udf_condition() is False
        assert config.is_sql_condition() is True

    def test_guard_config_from_dict(self):
        """Test creating GuardConfig from dictionary (YAML format)."""
        config_dict = {"condition": "udf:topic_quiz.validate_answer", "on_false": "skip"}
        config = GuardConfig.from_dict(config_dict)
        assert config.condition == "udf:topic_quiz.validate_answer"
        assert config.on_false == GuardBehavior.SKIP

    def test_guard_config_from_string_legacy(self):
        """Test creating GuardConfig from legacy string format."""
        config = GuardConfig.from_string("udf:validators.check_quality")
        assert config.condition == "udf:validators.check_quality"
        assert config.on_false == GuardBehavior.SKIP
        config = GuardConfig.from_string('status == "active"')
        assert config.condition == 'status == "active"'
        assert config.on_false == GuardBehavior.FILTER

    def test_guard_config_validation_invalid_condition(self):
        """Test that invalid conditions raise validation errors."""
        with pytest.raises(ValidationError, match="Invalid UDF expression format"):
            GuardConfig(condition="udf:invalid_format", on_false=GuardBehavior.SKIP)

    def test_guard_config_validation_dangerous_patterns(self):
        """Test that dangerous patterns are rejected."""
        with pytest.raises(ValidationError, match="potentially dangerous pattern"):
            GuardConfig(condition="udf:module.__import__", on_false=GuardBehavior.SKIP)

    def test_guard_behavior_enum_values(self):
        """Test GuardBehavior enum has expected values."""
        assert GuardBehavior.SKIP.value == "skip"
        assert GuardBehavior.FILTER.value == "filter"
        assert hasattr(GuardBehavior, "WRITE_TO")
        assert hasattr(GuardBehavior, "REPROCESS")


class TestConsolidatedGuardParser:
    """Test parsing consolidated guard configurations."""

    def test_parse_object_guard_config(self):
        """Test parsing object-style guard configuration."""
        guard_data = {"condition": "udf:validators.should_process", "on_false": "skip"}
        config = parse_guard_config(guard_data)
        assert isinstance(config, GuardConfig)
        assert config.condition == "udf:validators.should_process"
        assert config.on_false == GuardBehavior.SKIP

    def test_parse_string_guard_legacy(self):
        """Test parsing legacy string guard format."""
        config = parse_guard_config("udf:validators.check")
        assert config.on_false == GuardBehavior.SKIP
        config = parse_guard_config('field == "value"')
        assert config.on_false == GuardBehavior.FILTER

    def test_parse_invalid_guard_format(self):
        """Test parsing invalid guard formats raises errors."""
        with pytest.raises(ConfigValidationError, match="Guard must be string or dict"):
            parse_guard_config(123)
        with pytest.raises(ConfigValidationError, match="Guard dict must have 'condition' key"):
            parse_guard_config({"on_false": "skip"})


class TestFormatConverterIntegration:
    """Test integration with format converter for routing behavior."""

    def test_convert_skip_behavior_to_conditional_clause(self):
        """Test that skip behavior routes to conditional_clause."""
        from agent_actions.output.response.expander import ActionExpander

        action = {
            "name": "test_action",
            "intent": "Test action with skip guard",
            "guard": {"condition": "udf:validators.should_process", "on_false": "skip"},
            "model_vendor": "openai",
            "model_name": "gpt-4o-mini",
            "api_key": "TEST_API_KEY",
        }
        defaults = {}
        agent = {"agent_type": "test_action"}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, template_replacer
        )
        assert result.get("conditional_clause") == "validators.should_process"
        assert result.get("guard") is None

    def test_convert_filter_behavior_to_guard(self):
        """Test that filter behavior routes to guard config."""
        from agent_actions.output.response.expander import ActionExpander

        action = {
            "name": "test_action",
            "intent": "Test action with filter guard",
            "guard": {"condition": 'questionable != "Low Value"', "on_false": "filter"},
            "model_vendor": "openai",
            "model_name": "gpt-4o-mini",
            "api_key": "TEST_API_KEY",
        }
        defaults = {}
        agent = {"agent_type": "test_action"}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, template_replacer
        )
        assert result.get("guard") is not None
        assert result["guard"]["clause"] == 'questionable != "Low Value"'
        assert result["guard"]["scope"] == "item"
        assert result["guard"]["behavior"] == "filter"
        assert result.get("conditional_clause") is None

    def test_convert_skip_behavior_to_guard(self):
        """Test that SQL conditions with skip behavior route to guard config with skip behavior."""
        from agent_actions.output.response.expander import ActionExpander

        action = {
            "name": "test_action",
            "intent": "Test action with SQL skip guard",
            "guard": {"condition": 'questionable != "Low Value"', "on_false": "skip"},
            "model_vendor": "openai",
            "model_name": "gpt-4o-mini",
            "api_key": "TEST_API_KEY",
        }
        defaults = {}
        agent = {"agent_type": "test_action"}
        template_replacer = lambda x: x
        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, template_replacer
        )
        assert result.get("guard") is not None
        assert result["guard"]["clause"] == 'questionable != "Low Value"'
        assert result["guard"]["scope"] == "item"
        assert result["guard"]["behavior"] == "skip"
        assert result.get("conditional_clause") is None


class TestSchemaValidation:
    """Test schema validation for consolidated guard format."""

    def test_action_config_validates_consolidated_guard(self):
        """Test ActionConfig validates consolidated guard format."""
        from agent_actions.config.schema import ActionConfig

        action_data = {
            "name": "test_action",
            "intent": "Test action",
            "guard": {"condition": "udf:validators.check_quality", "on_false": "skip"},
        }
        action = ActionConfig(**action_data)
        assert action.guard["condition"] == "udf:validators.check_quality"
        assert action.guard["on_false"] == "skip"

    def test_action_config_validates_legacy_guard_string(self):
        """Test ActionConfig still accepts legacy string guards."""
        from agent_actions.config.schema import ActionConfig

        action_data = {
            "name": "test_action",
            "intent": "Test action",
            "guard": "udf:validators.check_quality",
        }
        action = ActionConfig(**action_data)
        assert action.guard == "udf:validators.check_quality"

    def test_action_config_rejects_invalid_guard(self):
        """Test ActionConfig rejects invalid guard configurations."""
        from agent_actions.config.schema import ActionConfig

        with pytest.raises(ValidationError, match="Invalid UDF expression format"):
            ActionConfig(
                name="test_action",
                intent="Test action",
                guard={"condition": "udf:invalid_format", "on_false": "skip"},
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
