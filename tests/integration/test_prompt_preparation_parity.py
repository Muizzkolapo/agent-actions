"""
Integration tests proving batch and realtime mode parity for PromptPreparationService.

These tests verify that PromptPreparationService produces identical outputs
when called with the same inputs in batch vs realtime mode.

This ensures guaranteed parity between modes and prevents divergent behavior.
"""

import pytest
from unittest.mock import patch
from agent_actions.prompt_generation.prompt_preparation_service import (
    PromptPreparationService
)


class TestPromptPreparationParity:
    """Test parity between batch and realtime modes."""

    def test_batch_realtime_produce_identical_prompts(self):
        """
        Test that batch and realtime modes produce identical formatted prompts
        for the same inputs.
        """
        agent_config = {
            'prompt': 'Process {source.text} and extract information',
            'agent_type': 'processor'
        }
        agent_name = 'processor'
        contents = {'data': 'test content'}
        source_content = {'text': 'hello world', 'metadata': {'author': 'test'}}

        # Mock the field context builder to return consistent data
        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
            mock_build.return_value = {
                'processor': {'data': 'test content'},
                'source': {'text': 'hello world', 'metadata': {'author': 'test'}}
            }

            # Call service in batch mode
            batch_result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name=agent_name,
                contents=contents,
                mode='batch',
                source_content=source_content
            )

            # Call service in realtime mode
            realtime_result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name=agent_name,
                contents=contents,
                mode='realtime',
                source_content=source_content
            )

            # Verify formatted prompts are identical
            assert batch_result.formatted_prompt == realtime_result.formatted_prompt
            assert 'hello world' in batch_result.formatted_prompt
            assert '{source.text}' not in batch_result.formatted_prompt

            # Verify metadata tracks mode correctly
            assert batch_result.metadata['mode'] == 'batch'
            assert realtime_result.metadata['mode'] == 'realtime'

    def test_batch_realtime_produce_identical_llm_context(self):
        """
        Test that batch and realtime modes produce identical LLM contexts
        for the same inputs (excluding mode-specific transformations).
        """
        agent_config = {
            'prompt': 'Analyze the data',
            'agent_type': 'analyzer'
        }
        agent_name = 'analyzer'
        contents = {
            'text': 'sample data',
            'value': 42,
            'metadata': {'source': 'test'}
        }

        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
            mock_build.return_value = {
                'analyzer': contents
            }

            # Call service in batch mode
            batch_result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name=agent_name,
                contents=contents,
                mode='batch'
            )

            # Call service in realtime mode
            realtime_result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name=agent_name,
                contents=contents,
                mode='realtime'
            )

            # Verify LLM contexts contain same fields
            assert set(batch_result.llm_context.keys()) == set(realtime_result.llm_context.keys())

            # Verify field values are identical
            for key in batch_result.llm_context:
                assert batch_result.llm_context[key] == realtime_result.llm_context[key], \
                    f"Field '{key}' differs between modes"

    def test_batch_realtime_handle_context_scope_identically(self):
        """
        Test that context_scope directives (observe/drop/passthrough) are
        applied identically in batch and realtime modes.
        """
        agent_config = {
            'prompt': 'Validate the data',
            'agent_type': 'validator',
            'context_scope': {
                'observe': ['extractor.entities'],
                'drop': ['source.api_key'],
                'passthrough': ['source.doc_id']
            }
        }
        agent_name = 'validator'
        contents = {
            'text': 'test data',
            'api_key': 'secret123',
            'doc_id': 'doc_456'
        }

        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
            mock_build.return_value = {
                'validator': {
                    'text': 'test data',
                    'api_key': 'secret123',
                    'doc_id': 'doc_456'
                },
                'extractor': {
                    'entities': ['entity1', 'entity2']
                },
                'source': {
                    'api_key': 'secret123',
                    'doc_id': 'doc_456',
                    'text': 'source text'
                }
            }

            # Call service in batch mode
            batch_result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name=agent_name,
                contents=contents,
                mode='batch',
                agent_indices={'extractor': 1, 'validator': 2}
            )

            # Call service in realtime mode
            realtime_result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name=agent_name,
                contents=contents,
                mode='realtime',
                agent_indices={'extractor': 1, 'validator': 2}
            )

            # Verify observe fields are tracked identically
            assert batch_result.metadata['observe_fields'] == realtime_result.metadata['observe_fields']

            # Verify drop fields are tracked identically
            assert batch_result.metadata['drop_fields'] == realtime_result.metadata['drop_fields']
            assert 'source.api_key' in batch_result.metadata['drop_fields']

            # Verify passthrough fields are tracked identically
            assert batch_result.metadata['passthrough_fields'] == realtime_result.metadata['passthrough_fields']

            # Verify api_key is NOT in LLM context (was dropped)
            assert 'api_key' not in batch_result.llm_context
            assert 'api_key' not in realtime_result.llm_context

    def test_batch_realtime_apply_few_shot_samples_identically(self):
        """
        Test that few-shot samples are applied identically in batch and
        realtime modes.

        This is a regression test for the bug where batch mode was NOT
        applying few-shot samples (fixed in Phase 1).
        """
        agent_config = {
            'prompt': 'Extract entities from text',
            'agent_type': 'extractor',
            'few_shot': 2  # Request few-shot samples
        }
        agent_name = 'extractor'
        contents = {'text': 'sample text'}

        # Mock SampleEnricher to track calls and return predictable output
        with patch('agent_actions.preprocessing.sample_enricher.SampleEnricher.append_few_shot_samples') as mock_samples:
            mock_samples.return_value = 'Extract entities from text\n\nfew shot samples:\n[sample1, sample2]'

            with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
                mock_build.return_value = {'extractor': contents}

                # Call service in batch mode
                batch_result = PromptPreparationService.prepare_prompt_with_context(
                    agent_config=agent_config,
                    agent_name=agent_name,
                    contents=contents,
                    mode='batch'
                )

                # Reset mock to track second call
                mock_samples.reset_mock()
                mock_samples.return_value = 'Extract entities from text\n\nfew shot samples:\n[sample1, sample2]'

                # Call service in realtime mode
                realtime_result = PromptPreparationService.prepare_prompt_with_context(
                    agent_config=agent_config,
                    agent_name=agent_name,
                    contents=contents,
                    mode='realtime'
                )

            # Verify SampleEnricher was called for BOTH modes
            assert mock_samples.call_count >= 1, "Few-shot samples not applied in one of the modes"

            # Verify formatted prompts are identical
            assert batch_result.formatted_prompt == realtime_result.formatted_prompt

            # Verify few-shot samples appear in the prompt
            assert 'few shot samples' in batch_result.formatted_prompt
            assert 'few shot samples' in realtime_result.formatted_prompt

            # This verifies the bug fix: batch mode now includes few-shot samples
            assert batch_result.formatted_prompt == realtime_result.formatted_prompt

    def test_batch_realtime_metadata_consistency(self):
        """
        Test that metadata structure is consistent between batch and realtime modes,
        even if some values differ (like mode field).
        """
        agent_config = {
            'prompt': 'Process data',
            'agent_type': 'processor',
            'context_scope': {
                'drop': ['source.secret']
            }
        }
        agent_name = 'processor'
        contents = {'data': 'test', 'secret': 'hidden'}

        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
            mock_build.return_value = {
                'processor': contents,
                'source': {'secret': 'hidden', 'public': 'visible'}
            }

            # Call service in batch mode
            batch_result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name=agent_name,
                contents=contents,
                mode='batch',
                source_content={'secret': 'hidden', 'public': 'visible'}
            )

            # Call service in realtime mode
            realtime_result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name=agent_name,
                contents=contents,
                mode='realtime',
                source_content={'secret': 'hidden', 'public': 'visible'}
            )

            # Verify metadata has same structure (same keys)
            assert set(batch_result.metadata.keys()) == set(realtime_result.metadata.keys())

            # Verify required metadata fields exist
            required_fields = [
                'mode', 'field_context_keys', 'observe_fields',
                'passthrough_fields', 'drop_fields', 'prompt_length', 'llm_context_keys'
            ]
            for field in required_fields:
                assert field in batch_result.metadata, f"Missing metadata field '{field}' in batch mode"
                assert field in realtime_result.metadata, f"Missing metadata field '{field}' in realtime mode"

            # Verify mode field correctly identifies the mode
            assert batch_result.metadata['mode'] == 'batch'
            assert realtime_result.metadata['mode'] == 'realtime'

    def test_batch_realtime_empty_inputs_handled_identically(self):
        """
        Test that empty/minimal inputs are handled identically in both modes.
        Edge case testing for robustness.
        """
        agent_config = {
            'prompt': 'Simple prompt',
            'agent_type': 'simple'
        }
        agent_name = 'simple'
        contents = {}  # Empty contents

        with patch('agent_actions.utilities.context_scope_processor.ContextScopeProcessor.build_field_context_with_history') as mock_build:
            mock_build.return_value = {'simple': {}}

            # Call service in batch mode
            batch_result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name=agent_name,
                contents=contents,
                mode='batch'
            )

            # Call service in realtime mode
            realtime_result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=agent_config,
                agent_name=agent_name,
                contents=contents,
                mode='realtime'
            )

            # Verify both modes handle empty inputs gracefully
            assert batch_result.formatted_prompt == realtime_result.formatted_prompt
            assert batch_result.formatted_prompt == 'Simple prompt'

            # Verify both produce valid (possibly empty) LLM contexts
            assert isinstance(batch_result.llm_context, dict)
            assert isinstance(realtime_result.llm_context, dict)

            # Verify metadata is populated
            assert batch_result.metadata['prompt_length'] == realtime_result.metadata['prompt_length']
