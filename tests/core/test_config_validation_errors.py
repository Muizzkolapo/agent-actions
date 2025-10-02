"""Tests for configuration validation error message quality."""

import pytest
import os
from agent_actions.core.parser.action_expander import ActionExpander
from agent_actions.integrations.providers.vendor_base import BaseVendorHandler
from agent_actions.core.exceptions import ConfigValidationError, ConfigurationError


class TestConfigValidationErrorMessages:
    """Verify error messages are helpful and actionable."""

    def test_missing_vendor_error_message_includes_fix(self):
        """Verify missing vendor error includes fix instructions."""
        agent = {
            'agent_type': 'test_action',
            'name': 'test_action',
            # Missing model_vendor
            'model_name': 'gpt-4',
            'api_key': 'TEST_KEY'
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            ActionExpander._validate_required_fields(agent, 'test_action')

        error = exc_info.value
        error_str = str(error)

        # Check error contains action name
        assert 'test_action' in error_str

        # Check error has helpful context
        assert error.context is not None
        assert 'action_name' in error.context
        assert 'missing_fields' in error.context

        # Check hint is provided
        assert 'hint' in error.context
        hint = error.context['hint'].lower()
        assert 'agent_actions.yml' in hint or 'workflow' in hint or 'action' in hint

    def test_missing_multiple_fields_error_lists_all(self):
        """Verify error lists all missing fields."""
        agent = {
            'agent_type': 'test_action',
            'name': 'test_action',
            # Missing all three required fields
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            ActionExpander._validate_required_fields(agent, 'test_action')

        error = exc_info.value
        missing = error.context['missing_fields']

        # Should list all 3 missing fields
        assert 'model_vendor' in missing
        assert 'model_name' in missing
        assert 'api_key' in missing
        assert len(missing) == 3

    def test_missing_single_field_shows_which_one(self):
        """Verify error clearly shows which single field is missing."""
        agent = {
            'agent_type': 'test_action',
            'name': 'test_action',
            'model_vendor': 'openai',
            'model_name': 'gpt-4',
            # Missing only api_key
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            ActionExpander._validate_required_fields(agent, 'test_action')

        error = exc_info.value
        missing = error.context['missing_fields']

        # Should only list api_key
        assert missing == ['api_key']

    def test_invalid_vendor_error_shows_valid_options(self):
        """Verify invalid vendor error shows valid vendors."""
        with pytest.raises(ConfigValidationError) as exc_info:
            ActionExpander._validate_vendor_exists('invalid_vendor', 'test_action')

        error = exc_info.value
        error_str = str(error)

        # Check shows the invalid value
        assert 'invalid_vendor' in error_str

        # Check shows valid options
        assert error.context['supported_vendors'] is not None
        supported = error.context['supported_vendors']
        assert 'openai' in supported
        assert 'anthropic' in supported
        assert 'gemini' in supported or 'google' in supported

        # Check has helpful hint
        assert 'hint' in error.context

    def test_env_var_error_shows_export_command(self):
        """Verify env var error shows how to set it."""
        agent_config = {
            'agent_type': 'test',
            'api_key': '${MISSING_VAR_12345}'
        }

        if 'MISSING_VAR_12345' in os.environ:
            del os.environ['MISSING_VAR_12345']

        with pytest.raises(ConfigurationError) as exc_info:
            BaseVendorHandler.get_api_key(agent_config)

        error = exc_info.value

        # Check hint contains export command
        assert 'hint' in error.context
        hint = error.context['hint']
        assert 'export' in hint
        assert 'MISSING_VAR_12345' in hint

    def test_error_context_includes_operation(self):
        """Verify errors include operation context for debugging."""
        agent = {
            'agent_type': 'test_action',
            'name': 'test_action',
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            ActionExpander._validate_required_fields(agent, 'test_action')

        error = exc_info.value

        # Should have operation context
        assert 'operation' in error.context
        assert error.context['operation'] == 'expand_actions_to_agents'

    def test_vendor_error_includes_action_name(self):
        """Verify vendor validation error includes action name in context."""
        with pytest.raises(ConfigValidationError) as exc_info:
            ActionExpander._validate_vendor_exists('bad_vendor', 'my_test_action')

        error = exc_info.value

        # Should include action name in context
        assert 'action' in error.context
        assert error.context['action'] == 'my_test_action'
