"""
Tests for LLM action schema validation.

Tests that LLM actions with output schemas have their field references
validated at config time, the same way UDFs are validated.
"""
import pytest
from agent_actions.response_processing.action_expander import ActionExpander


# Common defaults to avoid validation errors for required fields
DEFAULT_CONFIG = {
    'model_vendor': 'openai',
    'model_name': 'gpt-4',
    'api_key': 'test-key'
}


class TestLLMSchemaExtraction:
    """Test that LLM action schemas are extracted for validation."""

    def test_llm_action_with_list_schema_has_json_output_schema(self):
        """LLM actions with list-format schema should have json_output_schema."""
        config = {
            'name': 'test_workflow',
            'defaults': DEFAULT_CONFIG,
            'actions': [{
                'name': 'extract',
                'schema': [
                    {'id': 'facts', 'type': 'array', 'required': True},
                    {'id': 'confidence', 'type': 'number'}
                ]
            }]
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agent = result['test_workflow'][0]

        assert 'json_output_schema' in agent
        assert 'properties' in agent['json_output_schema']
        assert 'facts' in agent['json_output_schema']['properties']
        assert 'confidence' in agent['json_output_schema']['properties']

    def test_llm_action_without_schema_has_no_json_output_schema(self):
        """LLM actions without schema should not have json_output_schema."""
        config = {
            'name': 'test_workflow',
            'defaults': DEFAULT_CONFIG,
            'actions': [{
                'name': 'generate'
                # No schema - freeform output
            }]
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agent = result['test_workflow'][0]

        assert 'json_output_schema' not in agent or agent.get('json_output_schema') is None

    def test_tool_action_not_affected_by_llm_schema_extraction(self):
        """Tool actions should not be processed by _add_llm_output_schema."""
        config = {
            'name': 'test_workflow',
            'actions': [{
                'name': 'my_tool',
                'kind': 'tool',
                'impl': 'nonexistent.function'
            }]
        }
        # Should not raise, even though impl doesn't exist
        result = ActionExpander.expand_actions_to_agents(config)
        agent = result['test_workflow'][0]

        # Tool actions without valid UDF won't have json_output_schema
        assert agent.get('model_vendor') == 'tool'


class TestLLMSchemaValidation:
    """Test guard validation against LLM output schemas."""

    def test_invalid_field_reference_detected(self):
        """Guards referencing invalid LLM fields should produce errors."""
        config = {
            'name': 'test_workflow',
            'defaults': DEFAULT_CONFIG,
            'actions': [
                {
                    'name': 'extract',
                    'schema': [
                        {'id': 'facts', 'type': 'array'},
                        {'id': 'confidence', 'type': 'number'}
                    ]
                },
                {
                    'name': 'filter',
                    'dependencies': ['extract'],
                    'guard': 'extract.invalid_field > 0'
                }
            ]
        }
        result = ActionExpander.expand_actions_to_agents(config)
        errors = ActionExpander.validate_guard_references(
            result['test_workflow'], strict=False
        )

        assert len(errors) > 0
        assert 'invalid_field' in errors[0]

    def test_valid_field_reference_passes(self):
        """Guards referencing valid LLM fields should pass."""
        config = {
            'name': 'test_workflow',
            'defaults': DEFAULT_CONFIG,
            'actions': [
                {
                    'name': 'extract',
                    'schema': [
                        {'id': 'facts', 'type': 'array'},
                        {'id': 'confidence', 'type': 'number'}
                    ]
                },
                {
                    'name': 'filter',
                    'dependencies': ['extract'],
                    'guard': 'extract.confidence > 0.5'
                }
            ]
        }
        result = ActionExpander.expand_actions_to_agents(config)
        errors = ActionExpander.validate_guard_references(
            result['test_workflow'], strict=False
        )

        assert len(errors) == 0

    def test_llm_without_schema_skips_field_validation(self):
        """LLM actions without schema should skip field validation."""
        config = {
            'name': 'test_workflow',
            'defaults': DEFAULT_CONFIG,
            'actions': [
                {
                    'name': 'generate'
                    # No schema - freeform output
                },
                {
                    'name': 'process',
                    'dependencies': ['generate'],
                    'guard': 'generate.any_field > 0'
                }
            ]
        }
        result = ActionExpander.expand_actions_to_agents(config)
        # Should not raise, validation is skipped for actions without schemas
        errors = ActionExpander.validate_guard_references(
            result['test_workflow'], strict=False
        )
        # No errors because schema validation is skipped for actions without schemas
        assert len(errors) == 0

    def test_multiple_llm_actions_with_schemas(self):
        """Multiple LLM actions should all have their schemas validated."""
        config = {
            'name': 'test_workflow',
            'defaults': DEFAULT_CONFIG,
            'actions': [
                {
                    'name': 'extract_entities',
                    'schema': [
                        {'id': 'people', 'type': 'array'},
                        {'id': 'locations', 'type': 'array'}
                    ]
                },
                {
                    'name': 'analyze_sentiment',
                    'dependencies': ['extract_entities'],
                    'schema': [
                        {'id': 'sentiment', 'type': 'string'},
                        {'id': 'score', 'type': 'number'}
                    ]
                },
                {
                    'name': 'final_filter',
                    'dependencies': ['extract_entities', 'analyze_sentiment'],
                    # Reference top-level fields only (not .length which is a runtime property)
                    'guard': 'analyze_sentiment.score > 0.5 AND extract_entities.people exists'
                }
            ]
        }
        result = ActionExpander.expand_actions_to_agents(config)

        # Verify both LLM actions have schemas
        agents = result['test_workflow']
        assert agents[0].get('json_output_schema') is not None
        assert agents[1].get('json_output_schema') is not None

        # Valid references should pass
        errors = ActionExpander.validate_guard_references(agents, strict=False)
        assert len(errors) == 0

    def test_error_message_shows_available_fields(self):
        """Error messages should show available fields from LLM schema."""
        config = {
            'name': 'test_workflow',
            'defaults': DEFAULT_CONFIG,
            'actions': [
                {
                    'name': 'extract',
                    'schema': [
                        {'id': 'people', 'type': 'array'},
                        {'id': 'places', 'type': 'array'},
                        {'id': 'things', 'type': 'array'}
                    ]
                },
                {
                    'name': 'filter',
                    'dependencies': ['extract'],
                    'guard': 'extract.persons > 0'  # Typo: 'persons' instead of 'people'
                }
            ]
        }
        result = ActionExpander.expand_actions_to_agents(config)
        errors = ActionExpander.validate_guard_references(
            result['test_workflow'], strict=False
        )

        assert len(errors) > 0
        error_msg = errors[0].lower()
        # Error should mention the invalid field
        assert 'persons' in error_msg
        # Error should mention available fields
        assert 'people' in error_msg or 'available' in error_msg
