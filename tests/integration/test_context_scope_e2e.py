"""Integration tests for context_scope feature - essential tests only."""
import pytest
from unittest.mock import patch, MagicMock
from agent_actions.prompt_generation.data_generator import DataGenerator
from agent_actions.utilities.processor.processor_helpers import run_dynamic_agent


class TestContextScopeEndToEnd:
    """End-to-end integration tests for context_scope directives."""

    def test_observe_directive_e2e(self):
        """Test that observe directive sends fields to LLM context but not in output."""
        # Setup agent config with context_scope.observe
        agent_config = {
            'prompt': 'Analyze these facts: {source.candidate_facts}',
            'schema': {
                'analysis': 'string',
                'confidence': 'number'
            },
            'context_scope': {
                'observe': ['source.metadata', 'source.extracted_entities']
            },
            'model_vendor': 'tool'  # Use tool vendor for testing
        }

        generator = DataGenerator(
            agent_config=agent_config,
            agent_name='classifier',
            dependency_configs={},
            agent_indices={'classifier': 0}
        )

        # Setup source_content with all fields
        source_content = {
            'candidate_facts': ['fact1', 'fact2'],
            'metadata': {'count': 2, 'source': 'research'},
            'extracted_entities': ['entity1', 'entity2']
        }

        # Execute _format_prompt to test Phase 3
        formatted_prompt, _, llm_context, passthrough_fields = generator._format_prompt(
            {}, source_content=source_content
        )

        # Validate: metadata and extracted_entities in llm_context
        assert 'metadata' in llm_context
        assert llm_context['metadata'] == {'count': 2, 'source': 'research'}
        assert 'extracted_entities' in llm_context
        assert llm_context['extracted_entities'] == ['entity1', 'entity2']

        # Validate: candidate_facts still available for prompt rendering
        assert 'Analyze these facts:' in formatted_prompt
        assert '{source.metadata}' not in formatted_prompt  # Not in prompt (removed from context)

        # Validate: passthrough_fields empty (no passthrough directive)
        assert passthrough_fields == {}

    def test_drop_directive_e2e(self):
        """Test that drop directive blocks fields from LLM entirely."""
        # Setup agent config with context_scope.drop
        agent_config = {
            'prompt': 'Process data: {source.page_content}',
            'schema': {
                'result': 'string'
            },
            'context_scope': {
                'drop': ['source.api_key', 'source.credentials']
            },
            'model_vendor': 'tool'
        }

        generator = DataGenerator(
            agent_config=agent_config,
            agent_name='processor',
            dependency_configs={},
            agent_indices={'processor': 0}
        )

        contents = {}
        source_content = {
            'page_content': 'Sample text data',
            'api_key': 'secret_key_12345',
            'credentials': {'user': 'admin', 'pass': 'secret'}
        }

        # Execute _format_prompt
        formatted_prompt, filtered_contents, llm_context, passthrough_fields = generator._format_prompt(
            contents, source_content=source_content
        )

        # Validate: api_key and credentials NOT in llm_context
        assert 'api_key' not in llm_context
        assert 'credentials' not in llm_context

        # Validate: api_key and credentials NOT in passthrough
        assert 'api_key' not in passthrough_fields
        assert 'credentials' not in passthrough_fields

        # Validate: api_key and credentials NOT in filtered_contents (sent to LLM)
        assert 'api_key' not in filtered_contents, "Dropped field 'api_key' should be removed from contents"
        assert 'credentials' not in filtered_contents, "Dropped field 'credentials' should be removed from contents"

        # Validate: page_content still in prompt
        assert 'Process data:' in formatted_prompt

        # Validate: Cannot reference dropped fields in prompt
        # (They've been removed from prompt_context)
        assert '{source.api_key}' not in formatted_prompt

    def test_passthrough_directive_e2e(self):
        """Test that passthrough directive merges fields to output only."""
        # Setup agent config with context_scope.passthrough
        agent_config = {
            'prompt': 'Classify: {source.facts}',
            'schema': {
                'classification': 'string',
                'confidence': 'number'
            },
            'context_scope': {
                'passthrough': ['source.document_id', 'source.source_filename']
            },
            'model_vendor': 'tool'
        }

        generator = DataGenerator(
            agent_config=agent_config,
            agent_name='classifier',
            dependency_configs={},
            agent_indices={'classifier': 0}
        )

        source_content = {
            'facts': ['fact1', 'fact2'],
            'document_id': 'doc-123',
            'source_filename': 'report.pdf'
        }

        # Execute _format_prompt
        formatted_prompt, _, llm_context, passthrough_fields = generator._format_prompt(
            {}, source_content=source_content
        )

        # Validate: document_id and source_filename in passthrough_fields
        assert 'document_id' in passthrough_fields
        assert passthrough_fields['document_id'] == 'doc-123'
        assert 'source_filename' in passthrough_fields
        assert passthrough_fields['source_filename'] == 'report.pdf'

        # Validate: passthrough fields NOT in llm_context
        assert 'document_id' not in llm_context
        assert 'source_filename' not in llm_context

        # Validate: passthrough fields ARE in prompt_context (new behavior after fix)
        assert prompt_context.get('fact_extractor', {}).get('document_id') == 'doc-123'
        assert prompt_context.get('source', {}).get('source_filename') == 'report.pdf'

        # Validate: facts still available for prompt
        assert 'Classify:' in formatted_prompt

        # Test that run_dynamic_agent merges passthrough (Phase 4)
        with patch('agent_actions.utilities.processor_helpers.agent_builder.create_dynamic_agent') as mock_create:
            mock_create.return_value = [
                {
                    'source_guid': 'guid1',
                    'content': {
                        'classification': 'positive',
                        'confidence': 0.92
                    }
                }
            ]

            response, executed = run_dynamic_agent(
                agent_config,
                'classifier',
                {},
                formatted_prompt,
                llm_additional_context=llm_context,
                passthrough_fields=passthrough_fields
            )

            # Validate: passthrough fields merged into response
            assert response[0]['content']['classification'] == 'positive'
            assert response[0]['content']['document_id'] == 'doc-123'
            assert response[0]['content']['source_filename'] == 'report.pdf'

    def test_combined_directives_e2e(self):
        """Test all three directives working together in one workflow."""
        # Setup agent config with all three directives
        agent_config = {
            'prompt': 'Analyze: {source.summary}',
            'schema': {
                'analysis': 'string'
            },
            'context_scope': {
                'observe': ['source.reference_tables', 'source.metadata'],
                'drop': ['source.api_key'],
                'passthrough': ['source.document_id']
            },
            'model_vendor': 'tool'
        }

        generator = DataGenerator(
            agent_config=agent_config,
            agent_name='analyzer',
            dependency_configs={},
            agent_indices={'analyzer': 0}
        )

        source_content = {
            'summary': 'Research findings...',
            'reference_tables': {'ref1': 'data1'},
            'metadata': {'count': 5},
            'document_id': 'doc-456',
            'api_key': 'secret_123'
        }

        # Execute _format_prompt
        formatted_prompt, _, llm_context, passthrough_fields = generator._format_prompt(
            {}, source_content=source_content
        )

        # Validate OBSERVE: reference_tables and metadata in llm_context
        assert 'reference_tables' in llm_context
        assert 'metadata' in llm_context

        # Validate DROP: api_key nowhere
        assert 'api_key' not in llm_context
        assert 'api_key' not in passthrough_fields

        # Validate PASSTHROUGH: document_id in passthrough_fields only
        assert 'document_id' in passthrough_fields
        assert passthrough_fields['document_id'] == 'doc-456'
        assert 'document_id' not in llm_context

        # Validate prompt rendering
        assert 'Analyze:' in formatted_prompt

    def test_backward_compatibility(self):
        """Test that workflows WITHOUT context_scope work unchanged."""
        # Setup agent config WITHOUT context_scope
        agent_config = {
            'prompt': 'Process: {source.field}',
            'schema': {
                'output': 'string'
            },
            'model_vendor': 'tool'
            # No context_scope field
        }

        generator = DataGenerator(
            agent_config=agent_config,
            agent_name='processor',
            dependency_configs={},
            agent_indices={'processor': 0}
        )

        contents = {'data': 'test'}
        source_content = {'field': 'value', 'other': 'data'}

        # Execute _format_prompt
        formatted_prompt, _, llm_context, passthrough_fields = generator._format_prompt(
            contents, source_content=source_content
        )

        # Validate: Empty dicts returned when no context_scope
        assert llm_context == {}
        assert passthrough_fields == {}

        # Validate: Normal field referencing still works
        assert 'Process:' in formatted_prompt

        # Test run_dynamic_agent with empty dicts (should be no-op)
        with patch('agent_actions.utilities.processor_helpers.agent_builder.create_dynamic_agent') as mock_create:
            mock_create.return_value = [{'content': {'output': 'result'}}]

            response, executed = run_dynamic_agent(
                agent_config,
                'processor',
                contents,
                formatted_prompt,
                llm_additional_context=llm_context,
                passthrough_fields=passthrough_fields
            )

            # Validate: Response unchanged (no passthrough merge, no context appending)
            assert response[0]['content']['output'] == 'result'
            assert 'document_id' not in response[0]['content']  # No passthrough added
