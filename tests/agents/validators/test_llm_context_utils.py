"""Tests for LLM context computation utilities."""

import pytest
from agent_actions.agents.validators.llm_context_utils import LLMContextUtils


class TestComputeLLMContext:
    """Test computing LLM context from agent configurations."""

    def test_basic_schema_fields(self):
        """Should return all schema fields when no directives."""
        config = {
            'output_schema': {
                'properties': {
                    'summary': {},
                    'metrics': {},
                    'sentiment': {}
                }
            }
        }

        result = LLMContextUtils.compute_llm_context(config)

        assert result == {'summary', 'metrics', 'sentiment'}

    def test_empty_schema(self):
        """Should return empty set for empty schema."""
        config = {
            'output_schema': {
                'properties': {}
            }
        }

        result = LLMContextUtils.compute_llm_context(config)

        assert result == set()

    def test_missing_output_schema(self):
        """Should handle missing output_schema gracefully."""
        config = {}

        result = LLMContextUtils.compute_llm_context(config)

        assert result == set()

    def test_with_drops(self):
        """Should remove dropped fields from context."""
        config = {
            'output_schema': {
                'properties': {
                    'summary': {},
                    'metrics': {},
                    'internal_id': {},
                    'temp_data': {}
                }
            },
            'drops': ['internal_id', 'temp_data']
        }

        result = LLMContextUtils.compute_llm_context(config)

        assert result == {'summary', 'metrics'}
        assert 'internal_id' not in result
        assert 'temp_data' not in result

    def test_with_observe(self):
        """Should add observe fields to context (pass-through from input)."""
        config = {
            'output_schema': {
                'properties': {
                    'summary': {},
                    'sentiment': {}
                }
            },
            'observe': ['document_id', 'author', 'metadata']
        }

        result = LLMContextUtils.compute_llm_context(config)

        assert result == {'summary', 'sentiment', 'document_id', 'author', 'metadata'}

    def test_with_observe_only(self):
        """Should work with only observe fields (no schema fields)."""
        config = {
            'output_schema': {
                'properties': {}
            },
            'observe': ['original_id', 'timestamp']
        }

        result = LLMContextUtils.compute_llm_context(config)

        assert result == {'original_id', 'timestamp'}

    def test_with_return_collection(self):
        """Should add input_data when return_collection is True."""
        config = {
            'output_schema': {
                'properties': {
                    'result': {},
                    'count': {}
                }
            },
            'return_collection': True
        }

        result = LLMContextUtils.compute_llm_context(config)

        assert result == {'result', 'count', 'input_data'}

    def test_all_directives_combined(self):
        """Should correctly handle all directives together."""
        config = {
            'output_schema': {
                'properties': {
                    'summary': {},
                    'metrics': {},
                    'sentiment': {},
                    'internal_id': {},
                    'temp': {}
                }
            },
            'observe': ['document_id', 'author', 'original_text'],
            'drops': ['internal_id', 'temp'],
            'return_collection': True
        }

        result = LLMContextUtils.compute_llm_context(config)

        # Should have: schema - drops + observe + input_data
        assert result == {
            'summary', 'metrics', 'sentiment',  # From schema (not dropped)
            'document_id', 'author', 'original_text',  # From observe
            'input_data'  # From return_collection
        }
        assert 'internal_id' not in result  # Dropped
        assert 'temp' not in result  # Dropped

    def test_drops_takes_precedence_over_schema(self):
        """Should remove field even if in schema when in drops."""
        config = {
            'output_schema': {
                'properties': {
                    'field1': {},
                    'field2': {}
                }
            },
            'drops': ['field2']
        }

        result = LLMContextUtils.compute_llm_context(config)

        assert result == {'field1'}

    def test_drops_takes_precedence_over_observe(self):
        """Should remove field even if in observe when in drops."""
        config = {
            'output_schema': {
                'properties': {
                    'summary': {}
                }
            },
            'observe': ['field1', 'field2'],
            'drops': ['field2']
        }

        result = LLMContextUtils.compute_llm_context(config)

        assert result == {'summary', 'field1'}
        assert 'field2' not in result  # Dropped even though in observe

    def test_missing_directives(self):
        """Should handle missing drops/observe directives gracefully."""
        config = {
            'output_schema': {
                'properties': {
                    'summary': {},
                    'metrics': {}
                }
            }
            # No drops, no observe, no return_collection
        }

        result = LLMContextUtils.compute_llm_context(config)

        assert result == {'summary', 'metrics'}


class TestComputeOutputFields:
    """Test computing output fields from agent configurations."""

    def test_basic_output_fields(self):
        """Should return schema fields when no directives."""
        config = {
            'output_schema': {
                'properties': {
                    'summary': {},
                    'metrics': {}
                }
            }
        }

        result = LLMContextUtils.compute_output_fields(config)

        assert result == {'summary', 'metrics'}

    def test_output_with_drops(self):
        """Should exclude dropped fields from output."""
        config = {
            'output_schema': {
                'properties': {
                    'summary': {},
                    'temp': {}
                }
            },
            'drops': ['temp']
        }

        result = LLMContextUtils.compute_output_fields(config)

        assert result == {'summary'}

    def test_output_with_observe(self):
        """Should include observe fields in output."""
        config = {
            'output_schema': {
                'properties': {
                    'summary': {}
                }
            },
            'observe': ['original_id', 'metadata']
        }

        result = LLMContextUtils.compute_output_fields(config)

        assert result == {'summary', 'original_id', 'metadata'}

    def test_output_equals_llm_context(self):
        """Output fields should equal LLM context (without input_data)."""
        config = {
            'output_schema': {
                'properties': {
                    'summary': {},
                    'metrics': {},
                    'temp': {}
                }
            },
            'observe': ['document_id'],
            'drops': ['temp']
        }

        output_fields = LLMContextUtils.compute_output_fields(config)
        llm_context = LLMContextUtils.compute_llm_context(config)

        # Should be identical (no return_collection)
        assert output_fields == llm_context

    def test_output_vs_llm_context_with_return_collection(self):
        """Output fields should not include input_data (LLM context does)."""
        config = {
            'output_schema': {
                'properties': {
                    'result': {}
                }
            },
            'return_collection': True
        }

        output_fields = LLMContextUtils.compute_output_fields(config)
        llm_context = LLMContextUtils.compute_llm_context(config)

        assert output_fields == {'result'}
        assert llm_context == {'result', 'input_data'}
        assert 'input_data' not in output_fields  # Not in actual output file
        assert 'input_data' in llm_context  # But available to LLM

    def test_output_all_directives(self):
        """Should handle all directives correctly for output."""
        config = {
            'output_schema': {
                'properties': {
                    'summary': {},
                    'metrics': {},
                    'internal_id': {}
                }
            },
            'observe': ['original_id', 'author'],
            'drops': ['internal_id'],
            'return_collection': True  # Should NOT affect output_fields
        }

        result = LLMContextUtils.compute_output_fields(config)

        assert result == {'summary', 'metrics', 'original_id', 'author'}
        assert 'internal_id' not in result  # Dropped
        assert 'input_data' not in result  # return_collection doesn't affect output_fields
