"""
Tests for PromptPreparationService - Unified prompt preparation for batch and realtime modes.

This test suite validates that the service correctly orchestrates all prompt preparation
steps and produces consistent results across batch and realtime modes.
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from agent_actions.prompt_generation.prompt_preparation_service import (
    PromptPreparationService,
    PromptPreparationResult
)


class TestPromptPreparationServiceBasic:
    """Test basic prompt preparation without context_scope."""

    def test_prepare_prompt_basic_no_context_scope(self):
        """Test basic prompt preparation with no context_scope configured."""
        agent_config = {
            'prompt': 'Process the text',
            'agent_type': 'test_agent'
        }
        contents = {'text': 'test data'}

        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='test_agent',
            contents=contents,
            mode='realtime'
        )

        assert isinstance(result, PromptPreparationResult)
        assert result.formatted_prompt == 'Process the text'
        assert isinstance(result.llm_context, dict)
        assert result.passthrough_fields == {}
        assert result.metadata['mode'] == 'realtime'

    def test_prepare_prompt_with_field_references(self):
        """Test field reference substitution {action.field}."""
        agent_config = {
            'prompt': 'Process {source.text}',
            'agent_type': 'test_agent'
        }
        contents = {}

        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='test_agent',
            contents=contents,
            mode='realtime',
            source_content={'text': 'hello world'}
        )

        # Field reference should be replaced
        assert 'hello world' in result.formatted_prompt
        assert '{source.text}' not in result.formatted_prompt

    def test_prepare_prompt_empty_contents(self):
        """Test handling of empty contents."""
        agent_config = {
            'prompt': 'Simple prompt',
            'agent_type': 'test_agent'
        }

        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='test_agent',
            contents={},
            mode='realtime'
        )

        assert result.formatted_prompt == 'Simple prompt'
        assert isinstance(result.llm_context, dict)

    def test_prepare_prompt_none_contents(self):
        """Test handling of None contents (should treat as empty dict)."""
        agent_config = {
            'prompt': 'Simple prompt',
            'agent_type': 'test_agent'
        }

        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='test_agent',
            contents=None,
            mode='realtime'
        )

        assert result.formatted_prompt == 'Simple prompt'
        assert isinstance(result.llm_context, dict)


class TestPromptPreparationServiceContextScope:
    """Test context_scope directive handling."""

    def test_prepare_prompt_with_context_scope_observe(self):
        """Test context_scope.observe adds fields to LLM context."""
        agent_config = {
            'prompt': 'Validate the data',
            'agent_type': 'validator',
            'context_scope': {
                'observe': ['extractor.entities']
            }
        }
        contents = {'data': 'test'}

        # Mock the field context to include the upstream action
        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
            mock_build.return_value = {
                'validator': {'data': 'test'},
                'extractor': {'entities': ['entity1', 'entity2']}
            }

            result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name='validator',
                contents=contents,
                mode='realtime',
                agent_indices={'extractor': 1, 'validator': 2}
            )

            # Observed field should be in LLM context
            assert 'entities' in result.llm_context or 'extractor' in result.metadata['observe_fields']
            assert result.passthrough_fields == {}

    def test_prepare_prompt_with_context_scope_drop(self):
        """Test context_scope.drop removes fields from LLM context."""
        agent_config = {
            'prompt': 'Process data',
            'agent_type': 'processor',
            'context_scope': {
                'drop': ['source.api_key', 'source.password']
            }
        }
        contents = {'data': 'test', 'api_key': 'secret123', 'password': 'pass456'}

        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='processor',
            contents=contents,
            mode='batch',
            source_content={'api_key': 'secret123', 'password': 'pass456'}
        )

        # Dropped fields should not be in LLM context
        assert 'api_key' not in result.llm_context
        assert 'password' not in result.llm_context
        # But data should still be there
        assert 'data' in result.llm_context

    def test_prepare_prompt_with_context_scope_passthrough(self):
        """Test context_scope.passthrough marks fields for output merging."""
        agent_config = {
            'prompt': 'Extract entities',
            'agent_type': 'extractor',
            'context_scope': {
                'passthrough': ['source.doc_id', 'source.metadata']
            }
        }
        contents = {}

        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
            mock_build.return_value = {
                'source': {'doc_id': '123', 'metadata': {'author': 'test'}, 'text': 'content'}
            }

            result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name='extractor',
                contents=contents,
                mode='realtime',
                source_content={'doc_id': '123', 'metadata': {'author': 'test'}}
            )

            # Passthrough fields should be in result
            assert len(result.passthrough_fields) > 0 or 'doc_id' in result.metadata['passthrough_fields']

    def test_prepare_prompt_with_all_context_scope_directives(self):
        """Test combining observe, drop, and passthrough directives."""
        agent_config = {
            'prompt': 'Validate {{extractor.entities}} data',  # Now we CAN reference observed field in prompt
            'agent_type': 'validator',
            'context_scope': {
                'observe': ['extractor.entities'],
                'drop': ['source.api_key'],
                'passthrough': ['source.doc_id']
            }
        }
        contents = {'api_key': 'secret', 'doc_id': '123', 'text': 'data'}

        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
            mock_build.return_value = {
                'validator': {'api_key': 'secret', 'doc_id': '123', 'text': 'data'},
                'extractor': {'entities': ['entity1']},
                'source': {'doc_id': '123', 'api_key': 'secret'}
            }

            result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name='validator',
                contents=contents,
                mode='realtime',
                agent_indices={'extractor': 1, 'validator': 2}
            )

            # All directives should be tracked in metadata
            assert result.metadata['observe_fields'] or result.metadata['drop_fields'] or result.metadata['passthrough_fields']
            assert result.metadata['mode'] == 'realtime'
            # Observed fields should now be available in prompt template
            assert "Validate ['entity1'] data" in result.formatted_prompt


class TestPromptPreparationServiceModeSpecific:
    """Test mode-specific behavior (batch vs realtime)."""

    def test_prepare_prompt_batch_mode(self):
        """Test batch mode uses correct LLM context builder."""
        agent_config = {
            'prompt': 'Process data',
            'agent_type': 'processor'
        }
        contents = {'text': 'batch data'}

        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='processor',
            contents=contents,
            mode='batch'
        )

        assert result.metadata['mode'] == 'batch'
        assert isinstance(result.llm_context, dict)

    def test_prepare_prompt_realtime_mode(self):
        """Test realtime mode uses correct LLM context builder."""
        agent_config = {
            'prompt': 'Process data',
            'agent_type': 'processor'
        }
        contents = {'text': 'realtime data'}

        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='processor',
            contents=contents,
            mode='realtime'
        )

        assert result.metadata['mode'] == 'realtime'
        assert isinstance(result.llm_context, dict)

    def test_prepare_prompt_invalid_mode(self):
        """Test invalid mode raises ValueError."""
        agent_config = {
            'prompt': 'Process data',
            'agent_type': 'processor'
        }

        with pytest.raises(ValueError, match="Invalid mode"):
            # Directly call _build_llm_context with invalid mode
            PromptPreparationService._build_llm_context(
                mode='invalid',
                contents={},
                llm_additional_context={},
                context_scope=None
            )

    def test_batch_mode_with_tools_path(self):
        """Test batch mode with tools_path for function injection."""
        agent_config = {
            'prompt': 'Process data with dispatch_task("test_function")',
            'agent_type': 'processor'
        }
        contents = {'text': 'test'}

        # Mock the inject_function_outputs_into_prompt to verify it's called
        with patch('agent_actions.preprocessing.prompt_utils.PromptUtils.inject_function_outputs_into_prompt') as mock_inject:
            mock_inject.return_value = ('Processed prompt', {})

            result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name='processor',
                contents=contents,
                mode='batch',
                tools_path='/path/to/tools'
            )

            # Verify inject was called (batch mode specific)
            mock_inject.assert_called_once()
            # Verify it was called with JSON-serialized context
            args = mock_inject.call_args[0]
            assert args[1] == '/path/to/tools'
            # args[2] should be JSON string of llm_context
            assert isinstance(args[2], str)


class TestPromptPreparationServiceFewShot:
    """Test few-shot sample handling."""

    def test_prepare_prompt_with_few_shot_samples(self):
        """Test few-shot samples are appended to prompt."""
        agent_config = {
            'prompt': 'Extract entities',
            'agent_type': 'extractor',
            'few_shot': 2
        }
        contents = {'text': 'test'}

        # Mock SampleEnricher to verify it's called
        with patch('agent_actions.preprocessing.sample_enricher.SampleEnricher.append_few_shot_samples') as mock_samples:
            mock_samples.return_value = 'Extract entities\n\nfew shot samples:\n[...]'

            result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name='extractor',
                contents=contents,
                mode='realtime'
            )

            # Verify few-shot enrichment was called
            mock_samples.assert_called_once()
            # Verify it was called with correct parameters
            args = mock_samples.call_args[0]
            assert args[1] == agent_config
            assert args[2] == 'extractor'

    def test_prepare_prompt_batch_mode_includes_few_shot(self):
        """Test batch mode includes few-shot samples (bug fix verification)."""
        agent_config = {
            'prompt': 'Process data',
            'agent_type': 'processor',
            'few_shot': 1
        }
        contents = {'text': 'batch data'}

        # Mock SampleEnricher to verify it's called even in batch mode
        with patch('agent_actions.preprocessing.sample_enricher.SampleEnricher.append_few_shot_samples') as mock_samples:
            mock_samples.return_value = 'Process data\n\nfew shot samples:\n[...]'

            result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name='processor',
                contents=contents,
                mode='batch'
            )

            # This is the BUG FIX - batch mode should now call SampleEnricher
            mock_samples.assert_called_once()
            assert result.metadata['mode'] == 'batch'


class TestPromptPreparationServiceHistoricalNodes:
    """Test historical node loading."""

    def test_prepare_prompt_with_historical_node_loading(self):
        """Test historical node data is loaded when file_path provided."""
        agent_config = {
            'prompt': 'Validate {extractor.entities}',
            'agent_type': 'validator'
        }
        contents = {}
        file_path = '/path/to/node_2_validator/data.json'

        # Mock build_field_context_with_history to verify it's called with file_path
        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
            mock_build.return_value = {
                'validator': {},
                'extractor': {'entities': ['loaded_from_history']}
            }

            result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name='validator',
                contents=contents,
                mode='realtime',
                file_path=file_path,
                agent_indices={'extractor': 1, 'validator': 2}
            )

            # Verify historical loading was called with file_path
            mock_build.assert_called_once()
            call_kwargs = mock_build.call_args[1]
            assert call_kwargs['file_path'] == file_path


class TestPromptPreparationServiceMetadata:
    """Test metadata tracking."""

    def test_metadata_includes_all_required_fields(self):
        """Test result metadata contains all required fields."""
        agent_config = {
            'prompt': 'Process data',
            'agent_type': 'processor',
            'context_scope': {
                'observe': ['source.metadata'],
                'drop': ['source.api_key'],
                'passthrough': ['source.doc_id']
            }
        }
        contents = {'text': 'test'}

        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
            mock_build.return_value = {
                'processor': {'text': 'test'},
                'source': {'metadata': {}, 'api_key': 'secret', 'doc_id': '123'}
            }

            result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name='processor',
                contents=contents,
                mode='batch'
            )

            # Verify all metadata fields are present
            assert 'mode' in result.metadata
            assert 'field_context_keys' in result.metadata
            assert 'observe_fields' in result.metadata
            assert 'passthrough_fields' in result.metadata
            assert 'drop_fields' in result.metadata
            assert 'prompt_length' in result.metadata
            assert 'llm_context_keys' in result.metadata

            # Verify values are correct types
            assert isinstance(result.metadata['field_context_keys'], list)
            assert isinstance(result.metadata['observe_fields'], list)
            assert isinstance(result.metadata['passthrough_fields'], list)
            assert isinstance(result.metadata['drop_fields'], list)
            assert isinstance(result.metadata['prompt_length'], int)

    def test_metadata_tracks_field_transformations(self):
        """Test metadata correctly tracks field transformations."""
        agent_config = {
            'prompt': 'Process',
            'agent_type': 'processor',
            'context_scope': {
                'drop': ['source.secret']
            }
        }
        contents = {}

        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='processor',
            contents=contents,
            mode='realtime',
            source_content={'secret': 'value', 'public': 'data'}
        )

        # Drop directive should be tracked
        assert 'source.secret' in result.metadata['drop_fields']


class TestPromptPreparationServiceEdgeCases:
    """Test edge cases and error handling."""

    def test_prepare_prompt_with_none_optional_params(self):
        """Test all optional parameters as None doesn't break."""
        agent_config = {
            'prompt': 'Simple prompt',
            'agent_type': 'test'
        }

        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='test',
            contents={},
            mode='realtime',
            agent_indices=None,
            dependency_configs=None,
            source_content=None,
            loop_context=None,
            workflow_metadata=None,
            current_item=None,
            file_path=None,
            tools_path=None
        )

        assert isinstance(result, PromptPreparationResult)
        assert result.formatted_prompt == 'Simple prompt'

    def test_prepare_prompt_with_empty_agent_config(self):
        """Test minimal agent_config doesn't break."""
        agent_config = {
            'prompt': 'Test'
        }

        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='test',
            contents={}
        )

        assert isinstance(result, PromptPreparationResult)

    def test_prepare_prompt_non_dict_contents(self):
        """Test non-dict contents are handled gracefully."""
        agent_config = {
            'prompt': 'Process',
            'agent_type': 'test'
        }

        # Service should convert non-dict to empty dict
        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='test',
            contents='not a dict',  # Invalid type
            mode='realtime'
        )

        assert isinstance(result, PromptPreparationResult)
        assert isinstance(result.llm_context, dict)


class TestPromptPreparationServiceIntegration:
    """Integration tests verifying end-to-end behavior."""

    def test_full_pipeline_realtime_mode(self):
        """Test complete pipeline in realtime mode."""
        agent_config = {
            'prompt': 'Validate {source.text}',
            'agent_type': 'validator',
            'context_scope': {
                'observe': ['extractor.entities']
            }
        }
        contents = {'data': 'test'}

        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
            mock_build.return_value = {
                'validator': {'data': 'test'},
                'source': {'text': 'hello world'},
                'extractor': {'entities': ['entity1']}
            }

            result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name='validator',
                contents=contents,
                mode='realtime',
                source_content={'text': 'hello world'},
                agent_indices={'extractor': 1, 'validator': 2}
            )

            # Verify complete result
            assert 'hello world' in result.formatted_prompt  # Field reference replaced
            assert isinstance(result.llm_context, dict)  # LLM context built
            assert isinstance(result.metadata, dict)  # Metadata populated
            assert result.metadata['mode'] == 'realtime'

    def test_full_pipeline_batch_mode(self):
        """Test complete pipeline in batch mode."""
        agent_config = {
            'prompt': 'Process {source.text}',
            'agent_type': 'processor'
        }
        contents = {'text': 'batch data', 'id': '123'}

        result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name='processor',
            contents=contents,
            mode='batch',
            source_content={'text': 'batch data'},
            tools_path='/path/to/tools'
        )

        # Verify complete result
        assert isinstance(result.formatted_prompt, str)
        assert isinstance(result.llm_context, dict)
        assert 'text' in result.llm_context or 'id' in result.llm_context  # Row content preserved
        assert result.metadata['mode'] == 'batch'
