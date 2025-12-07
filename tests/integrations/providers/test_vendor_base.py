"""Tests for BaseVendorHandler API key validation."""
import pytest
import os
from agent_actions.llm_invocation.providers.vendor_base import BaseVendorHandler
from agent_actions.errors import ConfigurationError  # New modular pattern!

class TestVendorBaseAPIKeyValidation:
    """Test API key environment variable validation."""

    def test_api_key_env_var_not_set(self):
        """Test error when referenced env var doesn't exist."""
        agent_config = {'agent_type': 'test_agent', 'api_key': '${NONEXISTENT_TEST_KEY_12345}'}
        if 'NONEXISTENT_TEST_KEY_12345' in os.environ:
            del os.environ['NONEXISTENT_TEST_KEY_12345']
        with pytest.raises(ConfigurationError) as exc_info:
            BaseVendorHandler.get_api_key(agent_config)
        error = exc_info.value
        error_str = str(error)
        assert 'NONEXISTENT_TEST_KEY_12345' in error_str
        assert 'is not set' in error_str
        assert error.context['env_var'] == 'NONEXISTENT_TEST_KEY_12345'
        assert error.context['config_value'] == '${NONEXISTENT_TEST_KEY_12345}'
        assert 'export' in error.context['hint']

    def test_api_key_env_var_empty(self):
        """Test error when env var is set but empty."""
        agent_config = {'agent_type': 'test_agent', 'api_key': '${TEST_EMPTY_KEY_12345}'}
        os.environ['TEST_EMPTY_KEY_12345'] = ''
        try:
            with pytest.raises(ConfigurationError) as exc_info:
                BaseVendorHandler.get_api_key(agent_config)
            error = exc_info.value
            error_str = str(error)
            assert 'TEST_EMPTY_KEY_12345' in error_str
            assert 'empty' in error_str.lower()
            assert error.context['env_var'] == 'TEST_EMPTY_KEY_12345'
            assert 'export' in error.context['hint']
        finally:
            if 'TEST_EMPTY_KEY_12345' in os.environ:
                del os.environ['TEST_EMPTY_KEY_12345']

    def test_api_key_env_var_success(self):
        """Test successful env var resolution with ${} syntax."""
        os.environ['TEST_SUCCESS_KEY_12345'] = 'test-api-key-value'
        try:
            agent_config = {'agent_type': 'test_agent', 'api_key': '${TEST_SUCCESS_KEY_12345}'}
            result = BaseVendorHandler.get_api_key(agent_config)
            assert result == 'test-api-key-value'
        finally:
            if 'TEST_SUCCESS_KEY_12345' in os.environ:
                del os.environ['TEST_SUCCESS_KEY_12345']

    def test_api_key_legacy_format_success(self):
        """Test successful env var resolution with legacy format (no ${})."""
        os.environ['TEST_LEGACY_KEY_12345'] = 'legacy-api-key-value'
        try:
            agent_config = {'agent_type': 'test_agent', 'api_key': 'TEST_LEGACY_KEY_12345'}
            result = BaseVendorHandler.get_api_key(agent_config)
            assert result == 'legacy-api-key-value'
        finally:
            if 'TEST_LEGACY_KEY_12345' in os.environ:
                del os.environ['TEST_LEGACY_KEY_12345']

    def test_api_key_missing_from_config(self):
        """Test error when api_key field is missing from config."""
        agent_config = {'agent_type': 'test_agent'}
        with pytest.raises(ConfigurationError) as exc_info:
            BaseVendorHandler.get_api_key(agent_config)
        error = exc_info.value
        error_str = str(error)
        assert 'missing' in error_str.lower()
        assert 'hint' in error.context
        assert 'agent_actions.yml' in error.context['hint'] or 'workflow' in error.context['hint']