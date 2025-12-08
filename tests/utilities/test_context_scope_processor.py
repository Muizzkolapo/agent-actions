"""Tests for ContextScopeProcessor utility class."""
import pytest
from agent_actions.utilities.context_scope_processor import ContextScopeProcessor


class TestContextScopeProcessor:
    """Test suite for ContextScopeProcessor - essential tests only."""

    def test_apply_context_scope_all_directives(self):
        """Test apply_context_scope with all three directives working together."""
        # Setup field context with multiple actions and fields
        field_context = {
            'source': {
                'page_content': 'Sample text data',
                'api_key': 'secret_key_12345'
            },
            'fact_extractor': {
                'candidate_facts': ['fact1', 'fact2'],
                'extracted_entities': ['entity1', 'entity2'],
                'metadata': {'count': 2, 'source': 'research'},
                'document_id': 'doc-123'
            }
        }

        # Setup context_scope with all three directives
        context_scope = {
            'observe': ['fact_extractor.extracted_entities', 'fact_extractor.metadata'],
            'drop': ['source.api_key'],
            'passthrough': ['fact_extractor.document_id']
        }

        # Execute
        prompt_context, llm_context, passthrough_fields = ContextScopeProcessor.apply_context_scope(
            field_context, context_scope
        )

        # Validate OBSERVE directive
        assert 'extracted_entities' in llm_context
        assert llm_context['extracted_entities'] == ['entity1', 'entity2']
        assert 'metadata' in llm_context
        assert llm_context['metadata'] == {'count': 2, 'source': 'research'}
        # Observed fields should REMAIN in prompt_context for template rendering
        assert 'extracted_entities' in prompt_context.get('fact_extractor', {})
        assert prompt_context['fact_extractor']['extracted_entities'] == ['entity1', 'entity2']
        assert 'metadata' in prompt_context.get('fact_extractor', {})
        assert prompt_context['fact_extractor']['metadata'] == {'count': 2, 'source': 'research'}

        # Validate DROP directive
        assert 'api_key' not in prompt_context.get('source', {})
        assert 'api_key' not in llm_context
        assert 'api_key' not in passthrough_fields
        assert 'page_content' in prompt_context.get('source', {})  # Other fields remain

        # Validate PASSTHROUGH directive
        assert 'document_id' in passthrough_fields
        assert passthrough_fields['document_id'] == 'doc-123'
        assert prompt_context.get('fact_extractor', {}).get('document_id') == 'doc-123'  # Now available in prompt_context!
        assert 'document_id' not in llm_context

        # Validate fields NOT in any directive remain in prompt_context
        assert 'candidate_facts' in prompt_context.get('fact_extractor', {})
        assert prompt_context['fact_extractor']['candidate_facts'] == ['fact1', 'fact2']

    def test_format_llm_context(self):
        """Test formatting llm_context dict as readable text."""
        # Setup
        llm_context = {
            'extracted_entities': ['entity1', 'entity2', 'entity3'],
            'metadata': {
                'source': 'research_paper',
                'date': '2024-01-15',
                'count': 3
            },
            'reference_id': 'ref-456'
        }

        # Execute
        result = ContextScopeProcessor.format_llm_context(llm_context)

        # Validate
        assert result.startswith('Additional context:')
        assert 'extracted_entities:' in result
        assert 'metadata:' in result
        assert 'reference_id:' in result
        assert '"entity1"' in result
        assert '"research_paper"' in result
        assert '"ref-456"' in result

        # Test with empty context
        empty_result = ContextScopeProcessor.format_llm_context({})
        assert empty_result == ''

    def test_merge_passthrough_fields(self):
        """Test merging passthrough fields into LLM response."""
        # Test with structured response (with 'content' key)
        structured_response = [
            {
                'source_guid': 'guid-abc-123',
                'node_id': 'node_1_classifier',
                'content': {
                    'classification': 'positive',
                    'confidence': 0.92
                }
            },
            {
                'source_guid': 'guid-def-456',
                'node_id': 'node_1_classifier',
                'content': {
                    'classification': 'negative',
                    'confidence': 0.88
                }
            }
        ]

        passthrough_fields = {
            'document_id': 'doc-123',
            'original_filename': 'report.pdf'
        }

        # Execute
        result = ContextScopeProcessor.merge_passthrough_fields(
            structured_response, passthrough_fields
        )

        # Validate - passthrough fields merged into content
        assert result[0]['content']['classification'] == 'positive'
        assert result[0]['content']['confidence'] == 0.92
        assert result[0]['content']['document_id'] == 'doc-123'
        assert result[0]['content']['original_filename'] == 'report.pdf'

        assert result[1]['content']['classification'] == 'negative'
        assert result[1]['content']['confidence'] == 0.88
        assert result[1]['content']['document_id'] == 'doc-123'
        assert result[1]['content']['original_filename'] == 'report.pdf'

        # Test with flat response (no 'content' key)
        flat_response = [
            {'classification': 'positive', 'confidence': 0.95}
        ]

        flat_result = ContextScopeProcessor.merge_passthrough_fields(
            flat_response, passthrough_fields
        )

        # Validate - passthrough fields merged directly
        assert flat_result[0]['classification'] == 'positive'
        assert flat_result[0]['confidence'] == 0.95
        assert flat_result[0]['document_id'] == 'doc-123'
        assert flat_result[0]['original_filename'] == 'report.pdf'

        # Test with empty passthrough returns response unchanged
        unchanged = ContextScopeProcessor.merge_passthrough_fields(
            structured_response, {}
        )
        assert unchanged == structured_response
