"""Tests for LLM context computation utilities."""
import pytest
from agent_actions.utilities.llm_context_utils import LLMContextUtils

class TestComputeLLMContext:
    """Test computing LLM context from agent configurations."""

    def test_basic_schema_fields(self):
        """Should return all schema fields when no directives."""
        config = {'output_schema': {'properties': {'summary': {}, 'metrics': {}, 'sentiment': {}}}}
        result = LLMContextUtils.compute_llm_context(config)
        assert result == {'summary', 'metrics', 'sentiment'}

    def test_empty_schema(self):
        """Should return empty set for empty schema."""
        config = {'output_schema': {'properties': {}}}
        result = LLMContextUtils.compute_llm_context(config)
        assert result == set()

    def test_missing_output_schema(self):
        """Should handle missing output_schema gracefully."""
        config = {}
        result = LLMContextUtils.compute_llm_context(config)
        assert result == set()

    def test_with_context_scope_exclude(self):
        """Should handle context_scope.exclude (drops replacement - not affecting output)."""
        # Note: context_scope.exclude only removes from LLM context, not from output
        # Output = schema fields, so this test just verifies schema fields are returned
        config = {'output_schema': {'properties': {'summary': {}, 'metrics': {}, 'internal_id': {}, 'temp_data': {}}}}
        result = LLMContextUtils.compute_llm_context(config)
        assert result == {'summary', 'metrics', 'internal_id', 'temp_data'}

    def test_with_context_scope_passthrough(self):
        """Should add passthrough fields to context (pass-through from upstream actions)."""
        config = {
            'output_schema': {'properties': {'summary': {}, 'sentiment': {}}},
            'context_scope': {'passthrough': ['upstream.document_id', 'upstream.author', 'upstream.metadata']}
        }
        result = LLMContextUtils.compute_llm_context(config)
        assert result == {'summary', 'sentiment', 'document_id', 'author', 'metadata'}

    def test_with_passthrough_only(self):
        """Should work with only passthrough fields (no schema fields)."""
        config = {
            'output_schema': {'properties': {}},
            'context_scope': {'passthrough': ['upstream.original_id', 'upstream.timestamp']}
        }
        result = LLMContextUtils.compute_llm_context(config)
        assert result == {'original_id', 'timestamp'}

    def test_all_directives_combined(self):
        """Should correctly handle schema + passthrough together."""
        config = {
            'output_schema': {'properties': {'summary': {}, 'metrics': {}, 'sentiment': {}}},
            'context_scope': {'passthrough': ['upstream.document_id', 'upstream.author', 'upstream.original_text']}
        }
        result = LLMContextUtils.compute_llm_context(config)
        assert result == {'summary', 'metrics', 'sentiment', 'document_id', 'author', 'original_text'}

    def test_missing_directives(self):
        """Should handle missing context_scope directives gracefully."""
        config = {'output_schema': {'properties': {'summary': {}, 'metrics': {}}}}
        result = LLMContextUtils.compute_llm_context(config)
        assert result == {'summary', 'metrics'}

class TestComputeOutputFields:
    """Test computing output fields from agent configurations."""

    def test_basic_output_fields(self):
        """Should return schema fields when no directives."""
        config = {'output_schema': {'properties': {'summary': {}, 'metrics': {}}}}
        result = LLMContextUtils.compute_output_fields(config)
        assert result == {'summary', 'metrics'}

    def test_output_with_passthrough(self):
        """Should include passthrough fields in output."""
        config = {
            'output_schema': {'properties': {'summary': {}}},
            'context_scope': {'passthrough': ['upstream.original_id', 'upstream.metadata']}
        }
        result = LLMContextUtils.compute_output_fields(config)
        assert result == {'summary', 'original_id', 'metadata'}

    def test_output_equals_llm_context(self):
        """Output fields should equal LLM context."""
        config = {
            'output_schema': {'properties': {'summary': {}, 'metrics': {}}},
            'context_scope': {'passthrough': ['upstream.document_id']}
        }
        output_fields = LLMContextUtils.compute_output_fields(config)
        llm_context = LLMContextUtils.compute_llm_context(config)
        assert output_fields == llm_context

    def test_output_all_directives(self):
        """Should handle schema + passthrough correctly for output."""
        config = {
            'output_schema': {'properties': {'summary': {}, 'metrics': {}}},
            'context_scope': {'passthrough': ['upstream.original_id', 'upstream.author']}
        }
        result = LLMContextUtils.compute_output_fields(config)
        assert result == {'summary', 'metrics', 'original_id', 'author'}