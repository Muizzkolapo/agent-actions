"""
Integration tests verifying online and batch modes behave identically for schema compilation.

These tests are critical - they ensure the core principle:
"SAME PATHWAY FOR ONLINE AND BATCH - SAME VALIDATIONS APPLY"
"""

import pytest
import logging
from unittest.mock import patch, Mock

from agent_actions.agents.base.agent_builder import _prepare_schema as online_prepare_schema
from agent_actions.tasks.services.batch_service import BatchService


class TestSchemaParity:
    """Test that online and batch modes produce identical results."""

    @pytest.fixture
    def agent_config_with_inline_schema(self):
        """Agent config with inline schema."""
        return {
            "model_vendor": "openai",
            "schema": {
                "fields": [
                    {"id": "result", "type": "string", "required": True},
                    {"id": "confidence", "type": "number", "required": False}
                ]
            }
        }

    @pytest.fixture
    def agent_config_with_schema_name(self):
        """Agent config with schema_name reference."""
        return {
            "model_vendor": "openai",
            "schema_name": "test_schema"
        }

    @pytest.fixture
    def batch_service(self):
        """Create batch service instance."""
        return BatchService()

    def test_openai_schema_parity(self, agent_config_with_inline_schema):
        """Both modes produce identical schema for OpenAI."""
        # Mock schema loading/compilation
        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.core.parser.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {"base": "schema"}
                mock_compile.return_value = {"name": "test", "schema": {"type": "object"}}

                # Call online mode
                online_result = online_prepare_schema(agent_config_with_inline_schema, 'openai')

                # Call batch mode
                batch_service = BatchService()
                with patch.object(batch_service, 'provider') as mock_provider:
                    batch_result = batch_service._prepare_schema(agent_config_with_inline_schema, mock_provider)

                # CRITICAL: Results must be identical
                assert online_result == batch_result
                assert online_result is not None

    def test_anthropic_schema_parity(self):
        """Both modes produce identical schema for Anthropic."""
        config = {
            "model_vendor": "anthropic",
            "schema": {"fields": [{"id": "output", "type": "string"}]}
        }

        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.core.parser.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {"base": "schema"}
                mock_compile.return_value = [{"name": "test", "input_schema": {}}]

                online_result = online_prepare_schema(config, 'anthropic')

                batch_service = BatchService()
                with patch.object(batch_service, 'provider'):
                    batch_result = batch_service._prepare_schema(config)

                assert online_result == batch_result

    def test_gemini_schema_parity(self):
        """Both modes produce identical schema for Gemini."""
        config = {
            "model_vendor": "gemini",
            "schema": {"fields": [{"id": "answer", "type": "string"}]}
        }

        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict') as mock_construct:
            with patch('agent_actions.core.parser.schema_change.compile_unified_schema') as mock_compile:
                mock_construct.return_value = {"base": "schema"}
                mock_compile.return_value = {"name": "test", "schema": {}}

                online_result = online_prepare_schema(config, 'gemini')

                batch_service = BatchService()
                with patch.object(batch_service, 'provider'):
                    batch_result = batch_service._prepare_schema(config)

                assert online_result == batch_result

    def test_no_schema_parity(self):
        """Both modes return None when no schema provided."""
        config = {"model_vendor": "openai"}

        online_result = online_prepare_schema(config, 'openai')

        batch_service = BatchService()
        with patch.object(batch_service, 'provider'):
            batch_result = batch_service._prepare_schema(config)

        assert online_result is None
        assert batch_result is None
        assert online_result == batch_result

    def test_tool_vendor_parity(self):
        """Both modes return None for tool vendor."""
        config = {
            "model_vendor": "tool",
            "schema": {"fields": [{"id": "test", "type": "string"}]}
        }

        online_result = online_prepare_schema(config, 'tool')

        batch_service = BatchService()
        with patch.object(batch_service, 'provider'):
            batch_result = batch_service._prepare_schema(config)

        assert online_result is None
        assert batch_result is None

    def test_unsupported_vendor_parity_cohere(self, caplog):
        """Both modes warn and return None for cohere."""
        config = {
            "model_vendor": "cohere",
            "schema": {"fields": [{"id": "test", "type": "string"}]}
        }

        # Online mode
        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                online_result = online_prepare_schema(config, 'cohere')
        online_warnings = [r.message for r in caplog.records if r.levelname == 'WARNING']

        # Batch mode
        caplog.clear()
        batch_service = BatchService()
        with patch.object(batch_service, 'provider'):
            with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict'):
                with caplog.at_level(logging.WARNING):
                    batch_result = batch_service._prepare_schema(config)
        batch_warnings = [r.message for r in caplog.records if r.levelname == 'WARNING']

        # CRITICAL: Identical behavior
        assert online_result is None
        assert batch_result is None
        assert len(online_warnings) == 1
        assert len(batch_warnings) == 1
        assert online_warnings[0] == batch_warnings[0]

    def test_unsupported_vendor_parity_groq(self, caplog):
        """Both modes warn and return None for groq."""
        config = {
            "model_vendor": "groq",
            "schema": {"fields": [{"id": "test", "type": "string"}]}
        }

        # Online mode
        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                online_result = online_prepare_schema(config, 'groq')
        online_warnings = [r.message for r in caplog.records if r.levelname == 'WARNING']

        # Batch mode
        caplog.clear()
        batch_service = BatchService()
        with patch.object(batch_service, 'provider'):
            with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict'):
                with caplog.at_level(logging.WARNING):
                    batch_result = batch_service._prepare_schema(config)
        batch_warnings = [r.message for r in caplog.records if r.levelname == 'WARNING']

        # Identical warnings
        assert online_result is None
        assert batch_result is None
        assert online_warnings == batch_warnings


class TestWarningParity:
    """Test that warning messages are identical between modes."""

    def test_warning_message_identical(self, caplog):
        """Warning text is identical for both modes."""
        config = {
            "model_vendor": "mistral",
            "schema": {"fields": []}
        }

        # Capture online warning
        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                online_prepare_schema(config, 'mistral')
        online_msg = caplog.records[0].message

        # Capture batch warning
        caplog.clear()
        batch_service = BatchService()
        with patch.object(batch_service, 'provider'):
            with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict'):
                with caplog.at_level(logging.WARNING):
                    batch_service._prepare_schema(config)
        batch_msg = caplog.records[0].message

        assert online_msg == batch_msg

    def test_warning_log_level_identical(self, caplog):
        """Warning log level is identical for both modes."""
        config = {
            "model_vendor": "deepseek",
            "schema": {"fields": []}
        }

        # Online mode
        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict'):
            with caplog.at_level(logging.WARNING):
                online_prepare_schema(config, 'deepseek')
        online_level = caplog.records[0].levelname

        # Batch mode
        caplog.clear()
        batch_service = BatchService()
        with patch.object(batch_service, 'provider'):
            with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict'):
                with caplog.at_level(logging.WARNING):
                    batch_service._prepare_schema(config)
        batch_level = caplog.records[0].levelname

        assert online_level == batch_level == 'WARNING'

    def test_no_warning_when_no_schema(self, caplog):
        """Neither mode warns when no schema is provided."""
        config = {"model_vendor": "cohere"}

        # Online mode
        with caplog.at_level(logging.WARNING):
            online_result = online_prepare_schema(config, 'cohere')
        online_warnings = len(caplog.records)

        # Batch mode
        caplog.clear()
        batch_service = BatchService()
        with patch.object(batch_service, 'provider'):
            with caplog.at_level(logging.WARNING):
                batch_result = batch_service._prepare_schema(config)
        batch_warnings = len(caplog.records)

        assert online_result is None
        assert batch_result is None
        assert online_warnings == 0
        assert batch_warnings == 0

    def test_warning_content_format(self, caplog):
        """Warning format is consistent between modes."""
        config = {
            "model_vendor": "cohere",
            "schema_name": "my_schema"
        }

        # Online mode
        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.load_schema'):
            with caplog.at_level(logging.WARNING):
                online_prepare_schema(config, 'cohere')
        online_warning = caplog.records[0].message

        # Batch mode
        caplog.clear()
        batch_service = BatchService()
        with patch.object(batch_service, 'provider'):
            with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.load_schema'):
                with caplog.at_level(logging.WARNING):
                    batch_service._prepare_schema(config)
        batch_warning = caplog.records[0].message

        # Both should have same format
        assert online_warning == batch_warning
        assert 'cohere' in online_warning
        assert 'my_schema' in online_warning
        assert 'does not support schema validation' in online_warning


class TestSchemaCompilation:
    """Test compiled schema format consistency."""

    def test_compiled_format_openai(self):
        """Verify OpenAI compiled schema format."""
        config = {
            "model_vendor": "openai",
            "schema": {"fields": [{"id": "output", "type": "string", "required": True}]}
        }

        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict') as mock_construct:
            # Don't mock compile_unified_schema - test real compilation
            mock_construct.return_value = {"fields": [{"id": "output", "type": "string", "required": True}]}

            online_result = online_prepare_schema(config, 'openai')

            batch_service = BatchService()
            with patch.object(batch_service, 'provider'):
                batch_result = batch_service._prepare_schema(config)

            # Both should have OpenAI format
            assert online_result == batch_result
            assert 'name' in online_result  # OpenAI specific
            assert 'schema' in online_result  # OpenAI specific

    def test_compiled_format_anthropic(self):
        """Verify Anthropic compiled schema format."""
        config = {
            "model_vendor": "anthropic",
            "schema": {"fields": [{"id": "result", "type": "string", "required": True}]}
        }

        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict') as mock_construct:
            mock_construct.return_value = {"fields": [{"id": "result", "type": "string", "required": True}]}

            online_result = online_prepare_schema(config, 'anthropic')

            batch_service = BatchService()
            with patch.object(batch_service, 'provider'):
                batch_result = batch_service._prepare_schema(config)

            # Both should have Anthropic format (list with tool structure)
            assert online_result == batch_result
            assert isinstance(online_result, list)
            assert 'input_schema' in online_result[0]  # Anthropic specific

    def test_compiled_format_gemini(self):
        """Verify Gemini compiled schema format."""
        config = {
            "model_vendor": "gemini",
            "schema": {"fields": [{"id": "answer", "type": "string", "required": True}]}
        }

        with patch('agent_actions.agents.handlers.schema_handler.SchemaLoader.construct_schema_from_dict') as mock_construct:
            mock_construct.return_value = {"fields": [{"id": "answer", "type": "string", "required": True}]}

            online_result = online_prepare_schema(config, 'gemini')

            batch_service = BatchService()
            with patch.object(batch_service, 'provider'):
                batch_result = batch_service._prepare_schema(config)

            # Both should have Gemini format
            assert online_result == batch_result
            assert 'name' in online_result  # Gemini has name
            assert 'schema' in online_result  # Gemini has schema
