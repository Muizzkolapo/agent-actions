"""Tests for consolidated guard configuration with behavior control.

Following TDD approach - these tests define the expected API and behavior.
"""

import pytest
from agent_actions.core.utils.guard_parser import GuardParser, GuardType, GuardExpression
from agent_actions.core.utils.consolidated_guard import GuardConfig, GuardBehavior
from agent_actions.core.exceptions import ValidationError, ConfigValidationError


class TestGuardConfig:
    """Test the new GuardConfig class for consolidated guard behavior."""

    def test_guard_config_with_skip_behavior(self):
        """Test GuardConfig with skip behavior (passthrough)."""
        config = GuardConfig(
            condition="udf:validators.should_extract_facts",
            on_false=GuardBehavior.SKIP
        )

        assert config.condition == "udf:validators.should_extract_facts"
        assert config.on_false == GuardBehavior.SKIP
        assert config.is_udf_condition() is True
        assert config.is_sql_condition() is False

    def test_guard_config_with_filter_behavior(self):
        """Test GuardConfig with filter behavior (remove records)."""
        config = GuardConfig(
            condition='questionable != "Low Value"',
            on_false=GuardBehavior.FILTER
        )

        assert config.condition == 'questionable != "Low Value"'
        assert config.on_false == GuardBehavior.FILTER
        assert config.is_udf_condition() is False
        assert config.is_sql_condition() is True

    def test_guard_config_from_dict(self):
        """Test creating GuardConfig from dictionary (YAML format)."""
        config_dict = {
            "condition": "udf:topic_quiz.validate_answer",
            "on_false": "skip"
        }

        config = GuardConfig.from_dict(config_dict)

        assert config.condition == "udf:topic_quiz.validate_answer"
        assert config.on_false == GuardBehavior.SKIP

    def test_guard_config_from_string_legacy(self):
        """Test creating GuardConfig from legacy string format."""
        # Legacy UDF string should default to skip behavior
        config = GuardConfig.from_string("udf:validators.check_quality")

        assert config.condition == "udf:validators.check_quality"
        assert config.on_false == GuardBehavior.SKIP

        # Legacy SQL string should default to filter behavior
        config = GuardConfig.from_string('status == "active"')

        assert config.condition == 'status == "active"'
        assert config.on_false == GuardBehavior.FILTER

    def test_guard_config_validation_invalid_condition(self):
        """Test that invalid conditions raise validation errors."""
        with pytest.raises(ValidationError, match="Invalid UDF expression format"):
            GuardConfig(
                condition="udf:invalid_format",  # No module.function pattern
                on_false=GuardBehavior.SKIP
            )

    def test_guard_config_validation_dangerous_patterns(self):
        """Test that dangerous patterns are rejected."""
        with pytest.raises(ValidationError, match="potentially dangerous pattern"):
            GuardConfig(
                condition="udf:module.__import__",
                on_false=GuardBehavior.SKIP
            )

    def test_guard_behavior_enum_values(self):
        """Test GuardBehavior enum has expected values."""
        assert GuardBehavior.SKIP.value == "skip"
        assert GuardBehavior.FILTER.value == "filter"
        # Future behaviors
        assert hasattr(GuardBehavior, 'WRITE_TO')  # Will be added later
        assert hasattr(GuardBehavior, 'REPROCESS')  # Will be added later


class TestConsolidatedGuardParser:
    """Test parsing consolidated guard configurations."""

    def test_parse_object_guard_config(self):
        """Test parsing object-style guard configuration."""
        guard_data = {
            "condition": "udf:validators.should_process",
            "on_false": "skip"
        }

        config = GuardParser.parse_consolidated(guard_data)

        assert isinstance(config, GuardConfig)
        assert config.condition == "udf:validators.should_process"
        assert config.on_false == GuardBehavior.SKIP

    def test_parse_string_guard_legacy(self):
        """Test parsing legacy string guard format."""
        # UDF string
        config = GuardParser.parse_consolidated("udf:validators.check")
        assert config.on_false == GuardBehavior.SKIP  # Default for UDF

        # SQL string
        config = GuardParser.parse_consolidated('field == "value"')
        assert config.on_false == GuardBehavior.FILTER  # Default for SQL

    def test_parse_invalid_guard_format(self):
        """Test parsing invalid guard formats raises errors."""
        with pytest.raises(ConfigValidationError, match="Guard must be string or dict"):
            GuardParser.parse_consolidated(123)

        with pytest.raises(ConfigValidationError, match="Guard dict must have 'condition' key"):
            GuardParser.parse_consolidated({"on_false": "skip"})


class TestFormatConverterIntegration:
    """Test integration with format converter for routing behavior."""

    def test_convert_skip_behavior_to_conditional_clause(self):
        """Test that skip behavior routes to conditional_clause."""
        from agent_actions.core.parser.action_expander import ActionExpander

        action = {
            'name': 'test_action',
            'intent': 'Test action with skip guard',
            'guard': {
                'condition': 'udf:validators.should_process',
                'on_false': 'skip'
            },
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'TEST_API_KEY'
        }

        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, template_replacer
        )

        # Should route to conditional_clause for skip behavior
        assert result.get('conditional_clause') == 'validators.should_process'
        assert result.get('where_clause') is None

    def test_convert_filter_behavior_to_where_clause(self):
        """Test that filter behavior routes to where_clause."""
        from agent_actions.core.parser.action_expander import ActionExpander

        action = {
            'name': 'test_action',
            'intent': 'Test action with filter guard',
            'guard': {
                'condition': 'questionable != "Low Value"',
                'on_false': 'filter'
            },
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'TEST_API_KEY'
        }

        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, template_replacer
        )

        # Should route to where_clause for filter behavior
        assert result.get('where_clause') is not None
        assert result['where_clause']['clause'] == 'questionable != "Low Value"'
        assert result['where_clause']['scope'] == 'item'
        assert result['where_clause']['behavior'] == 'filter'
        assert result.get('conditional_clause') is None

    def test_convert_skip_behavior_to_where_clause(self):
        """Test that SQL conditions with skip behavior route to where_clause with skip behavior."""
        from agent_actions.core.parser.action_expander import ActionExpander

        action = {
            'name': 'test_action',
            'intent': 'Test action with SQL skip guard',
            'guard': {
                'condition': 'questionable != "Low Value"',
                'on_false': 'skip'
            },
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini',
            'api_key': 'TEST_API_KEY'
        }

        defaults = {}
        agent = {'agent_type': 'test_action'}
        template_replacer = lambda x: x

        result = ActionExpander._create_agent_from_action(
            action, defaults, agent, template_replacer
        )

        # Should route to where_clause with skip behavior
        assert result.get('where_clause') is not None
        assert result['where_clause']['clause'] == 'questionable != "Low Value"'
        assert result['where_clause']['scope'] == 'item'
        assert result['where_clause']['behavior'] == 'skip'
        assert result.get('conditional_clause') is None


class TestSchemaValidation:
    """Test schema validation for consolidated guard format."""

    def test_action_config_validates_consolidated_guard(self):
        """Test ActionConfig validates consolidated guard format."""
        from agent_actions.core.migration.new_format_schema import ActionConfig

        # Valid consolidated guard
        action_data = {
            'name': 'test_action',
            'intent': 'Test action',
            'guard': {
                'condition': 'udf:validators.check_quality',
                'on_false': 'skip'
            }
        }

        action = ActionConfig(**action_data)
        assert action.guard['condition'] == 'udf:validators.check_quality'
        assert action.guard['on_false'] == 'skip'

    def test_action_config_validates_legacy_guard_string(self):
        """Test ActionConfig still accepts legacy string guards."""
        from agent_actions.core.migration.new_format_schema import ActionConfig

        action_data = {
            'name': 'test_action',
            'intent': 'Test action',
            'guard': 'udf:validators.check_quality'
        }

        action = ActionConfig(**action_data)
        assert action.guard == 'udf:validators.check_quality'

    def test_action_config_rejects_invalid_guard(self):
        """Test ActionConfig rejects invalid guard configurations."""
        from agent_actions.core.migration.new_format_schema import ActionConfig

        with pytest.raises(ValidationError, match="Invalid UDF expression format"):
            ActionConfig(
                name='test_action',
                intent='Test action',
                guard={
                    'condition': 'udf:invalid_format',  # Invalid format
                    'on_false': 'skip'
                }
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])