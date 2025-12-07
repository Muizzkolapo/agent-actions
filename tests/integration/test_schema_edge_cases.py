"""
Integration tests for edge cases in unified schema compilation.

These tests verify the system handles unusual configurations, boundary
conditions, and error scenarios correctly.
"""
import pytest
import logging
from unittest.mock import patch, Mock
from agent_actions.response_processing.schema_change import prepare_schema_unified
from agent_actions.llm_invocation.realtime.services import SchemaService
from agent_actions.llm_invocation.batch.batch_service import BatchService

class TestMalformedConfigs:
    """Test handling of malformed or invalid configurations."""

    def test_both_inline_and_schema_name_online(self):
        """Online mode: inline schema takes precedence over schema_name."""
        config = {'schema': {'fields': [{'id': 'inline', 'type': 'string'}]}, 'schema_name': 'should_be_ignored'}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader') as mock_loader:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_loader.construct_schema_from_dict.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'schema'}
                SchemaService.prepare_schema(config, 'openai')
                mock_loader.construct_schema_from_dict.assert_called_once()
                mock_loader.load_schema.assert_not_called()

    def test_both_inline_and_schema_name_batch(self):
        """Batch mode: inline schema takes precedence over schema_name."""
        config = {'model_vendor': 'openai', 'schema': {'fields': [{'id': 'inline', 'type': 'string'}]}, 'schema_name': 'should_be_ignored'}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader') as mock_loader:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_loader.construct_schema_from_dict.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'schema'}
                batch_service = BatchService()
                with patch.object(batch_service, 'provider'):
                    batch_service._prepare_schema(config)
                mock_loader.construct_schema_from_dict.assert_called_once()
                mock_loader.load_schema.assert_not_called()

    def test_schema_with_empty_fields_online(self, caplog):
        """Online mode handles schema with empty fields array."""
        config = {'model_vendor': 'openai', 'schema': {'fields': []}}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {'fields': []}
                mock_compile.return_value = {'name': 'empty', 'schema': {}}
                with caplog.at_level(logging.WARNING):
                    result = SchemaService.prepare_schema(config, 'openai')
                assert result is not None
                assert len(caplog.records) == 0

    def test_schema_with_empty_fields_batch(self, caplog):
        """Batch mode handles schema with empty fields array."""
        config = {'model_vendor': 'openai', 'schema': {'fields': []}}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {'fields': []}
                mock_compile.return_value = {'name': 'empty', 'schema': {}}
                batch_service = BatchService()
                with patch.object(batch_service, 'provider'):
                    with caplog.at_level(logging.WARNING):
                        result = batch_service._prepare_schema(config)
                assert result is not None
                assert len(caplog.records) == 0

class TestVendorNameVariations:
    """Test vendor name handling (case sensitivity, whitespace, etc.)."""

    def test_uppercase_vendor_online(self):
        """Online mode handles uppercase vendor names."""
        config = {'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'schema'}
                result = SchemaService.prepare_schema(config, 'OPENAI')
                assert result is not None
                assert mock_compile.call_args[0][1] == 'OPENAI'

    def test_mixed_case_vendor_batch(self):
        """Batch mode handles mixed case vendor names."""
        config = {'model_vendor': 'OpenAI', 'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'schema'}
                batch_service = BatchService()
                with patch.object(batch_service, 'provider'):
                    result = batch_service._prepare_schema(config)
                assert result is not None

    def test_empty_vendor_string_online(self, caplog):
        """Online mode handles empty vendor string."""
        config = {'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                result = SchemaService.prepare_schema(config, '')
            assert result is None
            assert len(caplog.records) == 1
            assert caplog.records[0].levelname == 'WARNING'

    def test_empty_vendor_string_batch(self, caplog):
        """Batch mode handles empty vendor string."""
        config = {'model_vendor': '', 'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict'):
            batch_service = BatchService()
            with patch.object(batch_service, 'provider') as mock_provider:
                type(mock_provider).__name__ = 'OpenAIBatchProvider'
                with caplog.at_level(logging.WARNING):
                    result = batch_service._prepare_schema(config)
                assert result is not None or len(caplog.records) == 1

class TestSchemaNameReferences:
    """Test schema_name reference loading edge cases."""

    def test_nonexistent_schema_name_online(self):
        """Online mode handles nonexistent schema_name reference."""
        config = {'schema_name': 'nonexistent_schema'}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.load_schema') as mock_load:
            mock_load.side_effect = FileNotFoundError('Schema not found')
            with pytest.raises(FileNotFoundError):
                SchemaService.prepare_schema(config, 'openai')

    def test_nonexistent_schema_name_batch(self):
        """Batch mode handles nonexistent schema_name reference."""
        config = {'model_vendor': 'openai', 'schema_name': 'nonexistent_schema'}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.load_schema') as mock_load:
            mock_load.side_effect = FileNotFoundError('Schema not found')
            batch_service = BatchService()
            with patch.object(batch_service, 'provider'):
                with pytest.raises(FileNotFoundError):
                    batch_service._prepare_schema(config)

    def test_empty_schema_name_online(self):
        """Online mode handles empty schema_name value."""
        config = {'schema_name': ''}
        result = SchemaService.prepare_schema(config, 'openai')
        assert result is None

    def test_empty_schema_name_batch(self):
        """Batch mode handles empty schema_name value."""
        config = {'model_vendor': 'openai', 'schema_name': ''}
        batch_service = BatchService()
        with patch.object(batch_service, 'provider'):
            result = batch_service._prepare_schema(config)
        assert result is None

class TestBatchProviderFallback:
    """Test batch mode's vendor extraction from provider when config is missing."""

    def test_batch_extracts_vendor_from_openai_provider(self):
        """Batch mode extracts 'openai' from OpenAIBatchProvider."""
        config = {'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'schema'}
                batch_service = BatchService()
                with patch.object(batch_service, 'provider') as mock_provider:
                    type(mock_provider).__name__ = 'OpenAIBatchProvider'
                    result = batch_service._prepare_schema(config)
                    assert result is not None
                    assert mock_compile.call_args[0][1] == 'openai'

    def test_batch_extracts_vendor_from_anthropic_provider(self):
        """Batch mode extracts 'anthropic' from AnthropicBatchProvider."""
        config = {'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {'base': 'schema'}
                mock_compile.return_value = [{'tool': 'schema'}]
                batch_service = BatchService()
                with patch.object(batch_service, 'provider') as mock_provider:
                    type(mock_provider).__name__ = 'AnthropicBatchProvider'
                    result = batch_service._prepare_schema(config)
                    assert result is not None
                    assert mock_compile.call_args[0][1] == 'anthropic'

    def test_batch_config_vendor_overrides_provider(self):
        """Batch mode prioritizes config vendor over provider extraction."""
        config = {'model_vendor': 'gemini', 'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {'base': 'schema'}
                mock_compile.return_value = {'compiled': 'schema'}
                batch_service = BatchService()
                with patch.object(batch_service, 'provider') as mock_provider:
                    type(mock_provider).__name__ = 'OpenAIBatchProvider'
                    result = batch_service._prepare_schema(config)
                    assert result is not None
                    assert mock_compile.call_args[0][1] == 'gemini'

class TestCompilationErrorHandling:
    """Test error handling during schema compilation."""

    def test_compilation_error_returns_none_online(self, caplog):
        """Online mode handles compilation errors gracefully."""
        config = {'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        from agent_actions.errors import ConfigValidationError  # New modular pattern!
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {'base': 'schema'}
                mock_compile.side_effect = ConfigValidationError('model_vendor', 'Unsupported vendor')
                with caplog.at_level(logging.WARNING):
                    result = SchemaService.prepare_schema(config, 'unsupported')
                assert result is None
                assert len(caplog.records) == 1
                assert 'does not support schema validation' in caplog.records[0].message

    def test_compilation_error_returns_none_batch(self, caplog):
        """Batch mode handles compilation errors gracefully."""
        config = {'model_vendor': 'unsupported', 'schema': {'fields': [{'id': 'test', 'type': 'string'}]}}
        from agent_actions.errors import ConfigValidationError  # New modular pattern!
        with patch('agent_actions.response_processing.schema_loader.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.response_processing.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {'base': 'schema'}
                mock_compile.side_effect = ConfigValidationError('model_vendor', 'Unsupported vendor')
                batch_service = BatchService()
                with patch.object(batch_service, 'provider'):
                    with caplog.at_level(logging.WARNING):
                        result = batch_service._prepare_schema(config)
                assert result is None
                assert len(caplog.records) == 1
                assert 'does not support schema validation' in caplog.records[0].message