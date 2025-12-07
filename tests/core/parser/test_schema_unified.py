"""
Unit tests for prepare_schema_unified() function.

These tests verify the unified schema preparation logic works correctly
for all vendors and edge cases.
"""
import pytest
import logging
from unittest.mock import patch, Mock, MagicMock
from agent_actions.response_processing.schema_change import prepare_schema_unified
from agent_actions.errors import ConfigValidationError  # New modular pattern!

class TestPrepareSchemaUnified:
    """Test basic functionality of prepare_schema_unified()."""

    @pytest.fixture
    def sample_agent_config_inline(self):
        """Agent config with inline schema."""
        return {'schema': {'fields': [{'id': 'name', 'type': 'string', 'required': True}, {'id': 'age', 'type': 'integer', 'required': False}]}}

    @pytest.fixture
    def sample_agent_config_schema_name(self):
        """Agent config with schema_name reference."""
        return {'schema_name': 'test_schema'}

    def test_supported_vendor_openai(self, sample_agent_config_inline):
        """OpenAI vendor returns compiled schema."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader') as mock_loader:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_loader.construct_schema_from_dict.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'openai_schema'}
                result = prepare_schema_unified(sample_agent_config_inline, 'openai')
                assert result == {'compiled': 'openai_schema'}
                mock_compile.assert_called_once_with({'base': 'schema'}, 'openai')

    def test_supported_vendor_anthropic(self, sample_agent_config_inline):
        """Anthropic vendor returns compiled schema."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader') as mock_loader:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_loader.construct_schema_from_dict.return_value = {'base': 'schema'}
                mock_compile.return_value = [{'compiled': 'anthropic_schema'}]
                result = prepare_schema_unified(sample_agent_config_inline, 'anthropic')
                assert result == [{'compiled': 'anthropic_schema'}]
                mock_compile.assert_called_once_with({'base': 'schema'}, 'anthropic')

    def test_supported_vendor_gemini(self, sample_agent_config_inline):
        """Gemini vendor returns compiled schema."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader') as mock_loader:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_loader.construct_schema_from_dict.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'gemini_schema'}
                result = prepare_schema_unified(sample_agent_config_inline, 'gemini')
                assert result == {'compiled': 'gemini_schema'}
                mock_compile.assert_called_once_with({'base': 'schema'}, 'gemini')

    def test_supported_vendor_ollama(self, sample_agent_config_inline):
        """Ollama vendor returns compiled schema."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader') as mock_loader:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_loader.construct_schema_from_dict.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'ollama_schema'}
                result = prepare_schema_unified(sample_agent_config_inline, 'ollama')
                assert result == {'compiled': 'ollama_schema'}
                mock_compile.assert_called_once_with({'base': 'schema'}, 'ollama')

    def test_inline_schema(self, sample_agent_config_inline):
        """Inline schema is processed correctly."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader') as mock_loader:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_loader.construct_schema_from_dict.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'schema'}
                result = prepare_schema_unified(sample_agent_config_inline, 'openai')
                assert result is not None
                mock_loader.construct_schema_from_dict.assert_called_once_with(sample_agent_config_inline['schema'])

    def test_schema_name_reference(self, sample_agent_config_schema_name):
        """Schema name reference is loaded correctly."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader') as mock_loader:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_loader.load_schema.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'schema'}
                result = prepare_schema_unified(sample_agent_config_schema_name, 'openai')
                assert result is not None
                mock_loader.load_schema.assert_called_once_with('test_schema')

    def test_no_schema_returns_none(self):
        """Returns None when no schema is provided."""
        config = {}
        result = prepare_schema_unified(config, 'openai')
        assert result is None

    def test_tool_vendor_always_none(self, sample_agent_config_inline):
        """Tool vendor always returns None, even with schema."""
        result = prepare_schema_unified(sample_agent_config_inline, 'tool')
        assert result is None

class TestUnsupportedVendors:
    """Test behavior with unsupported vendors."""

    @pytest.fixture
    def agent_config_with_schema(self):
        return {'schema': {'fields': [{'id': 'result', 'type': 'string'}]}}

    def test_cohere_warns_and_returns_none(self, agent_config_with_schema, caplog):
        """Cohere vendor warns and returns None."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                result = prepare_schema_unified(agent_config_with_schema, 'cohere')
            assert result is None
            assert len(caplog.records) == 1
            assert caplog.records[0].levelname == 'WARNING'

    def test_mistral_warns_and_returns_none(self, agent_config_with_schema, caplog):
        """Mistral vendor warns and returns None."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                result = prepare_schema_unified(agent_config_with_schema, 'mistral')
            assert result is None
            assert len(caplog.records) == 1

    def test_groq_warns_and_returns_none(self, agent_config_with_schema, caplog):
        """Groq vendor warns and returns None."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                result = prepare_schema_unified(agent_config_with_schema, 'groq')
            assert result is None
            assert len(caplog.records) == 1

    def test_deepseek_warns_and_returns_none(self, agent_config_with_schema, caplog):
        """DeepSeek vendor warns and returns None."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                result = prepare_schema_unified(agent_config_with_schema, 'deepseek')
            assert result is None
            assert len(caplog.records) == 1

    def test_warning_message_format(self, agent_config_with_schema, caplog):
        """Warning message has correct format."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                prepare_schema_unified(agent_config_with_schema, 'cohere')
            warning_msg = caplog.records[0].message
            assert 'does not support schema validation' in warning_msg

    def test_warning_includes_vendor_name(self, agent_config_with_schema, caplog):
        """Warning includes the vendor name."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                prepare_schema_unified(agent_config_with_schema, 'cohere')
            warning_msg = caplog.records[0].message
            assert 'cohere' in warning_msg.lower()

    def test_warning_includes_schema_name(self, caplog):
        """Warning includes the schema name."""
        config = {'schema_name': 'my_test_schema'}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.load_schema'):
            with caplog.at_level(logging.WARNING):
                prepare_schema_unified(config, 'cohere')
            warning_msg = caplog.records[0].message
            assert 'my_test_schema' in warning_msg

    def test_warning_includes_suggestions(self, agent_config_with_schema, caplog):
        """Warning includes suggested vendors."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                prepare_schema_unified(agent_config_with_schema, 'cohere')
            warning_msg = caplog.records[0].message
            assert 'openai' in warning_msg
            assert 'anthropic' in warning_msg
            assert 'gemini' in warning_msg
            assert 'ollama' in warning_msg

    def test_warning_log_level(self, agent_config_with_schema, caplog):
        """Warning is logged at WARNING level."""
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                prepare_schema_unified(agent_config_with_schema, 'cohere')
            assert caplog.records[0].levelname == 'WARNING'

class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_vendor_string(self, caplog):
        """Empty vendor string triggers unsupported vendor warning."""
        config = {'schema': {'fields': []}}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                result = prepare_schema_unified(config, '')
            assert result is None
            assert len(caplog.records) == 1
            assert caplog.records[0].levelname == 'WARNING'

    def test_case_insensitive_vendor(self):
        """Vendor names are case-insensitive."""
        config = {'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict') as mock_loader:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_loader.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'schema'}
                result = prepare_schema_unified(config, 'OpenAI')
                assert result is not None
                assert mock_compile.call_args[0][1] == 'OpenAI'

    def test_both_inline_and_schema_name(self):
        """Inline schema takes precedence over schema_name."""
        config = {'schema': {'fields': [{'id': 'inline', 'type': 'string'}]}, 'schema_name': 'should_be_ignored'}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader') as mock_loader:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_loader.construct_schema_from_dict.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'schema'}
                result = prepare_schema_unified(config, 'openai')
                mock_loader.construct_schema_from_dict.assert_called_once()
                mock_loader.load_schema.assert_not_called()

    def test_tool_vendor_ignores_schema(self):
        """Tool vendor returns None even with valid schema."""
        config = {'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        result = prepare_schema_unified(config, 'tool')
        assert result is None

    def test_no_warning_for_tool_vendor(self, caplog):
        """Tool vendor doesn't trigger warning."""
        config = {'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        with caplog.at_level(logging.WARNING):
            result = prepare_schema_unified(config, 'tool')
        assert result is None
        assert len(caplog.records) == 0

    def test_no_warning_when_no_schema(self, caplog):
        """No warning when no schema is provided."""
        config = {}
        with caplog.at_level(logging.WARNING):
            result = prepare_schema_unified(config, 'cohere')
        assert result is None
        assert len(caplog.records) == 0