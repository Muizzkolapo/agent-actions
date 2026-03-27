"""
Tests for field prefix pattern validation in context_scope.

Field prefix patterns (e.g., "extract_raw_qa_") are used for loop consumption
where merged outputs have prefixed field names like "extract_raw_qa_1_questions".
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_inference import infer_dependencies
from agent_actions.prompt.context.scope_namespace import _extract_allowed_fields_per_dependency
from agent_actions.prompt.context.scope_parsing import (
    extract_action_names_from_context_scope,
    parse_field_reference,
)


class TestFieldPrefixPatternParsing:
    """Test parsing of field prefix patterns."""

    def test_parse_field_prefix_pattern(self):
        """Test that field prefix patterns are parsed correctly."""
        # Field prefix pattern for loop consumption
        action_name, field_name = parse_field_reference("extract_raw_qa_")

        assert action_name == "extract_raw_qa"
        assert field_name == "_"  # Special marker for field prefix pattern

    def test_parse_regular_field_reference(self):
        """Test that regular field references still work."""
        action_name, field_name = parse_field_reference("action_A.field1")

        assert action_name == "action_A"
        assert field_name == "field1"

    def test_parse_wildcard_reference(self):
        """Test parsing wildcard references."""
        action_name, field_name = parse_field_reference("action_A.*")

        assert action_name == "action_A"
        assert field_name == "*"

    def test_invalid_field_prefix_pattern_empty_base(self):
        """Test that empty base name in field prefix pattern raises error."""
        with pytest.raises(ValueError, match="Base name cannot be empty"):
            parse_field_reference("_")


class TestFieldPrefixPatternValidation:
    """Test validation of dependencies with field prefix patterns."""

    def test_loop_dependencies_validated_with_field_prefix_pattern(self):
        """Test that loop iteration dependencies are validated against field prefix pattern."""
        # After orchestration expansion:
        # - dependencies: ['extract_raw_qa_1', 'extract_raw_qa_2', 'extract_raw_qa_3']
        # - context_scope: {observe: ['extract_raw_qa_']}
        dependencies = ["extract_raw_qa_1", "extract_raw_qa_2", "extract_raw_qa_3"]
        context_scope = {
            "observe": ["extract_raw_qa_"]  # Field prefix pattern
        }

        # Should not raise - field prefix pattern covers all loop iterations
        allowed_fields = _extract_allowed_fields_per_dependency(
            dependencies, context_scope, action_name="flatten_questions"
        )

        # All loop iterations should be allowed (wildcard via field prefix pattern)
        assert allowed_fields["extract_raw_qa_1"] is None  # None = all fields
        assert allowed_fields["extract_raw_qa_2"] is None
        assert allowed_fields["extract_raw_qa_3"] is None

    def test_loop_dependency_without_context_scope_reference_fails(self):
        """Test that loop dependencies without context_scope reference raise error."""
        dependencies = ["extract_raw_qa_1"]
        context_scope = {
            "observe": ["other_action.*"]  # Missing extract_raw_qa_ reference
        }

        with pytest.raises(
            ConfigurationError, match="Dependency 'extract_raw_qa_1' declared but not referenced"
        ):
            _extract_allowed_fields_per_dependency(
                dependencies, context_scope, action_name="test_action"
            )

    def test_field_prefix_pattern_with_specific_fields_not_allowed(self):
        """Test that field prefix patterns don't support specific field references."""
        # This is correct behavior - field prefix patterns match ALL fields
        dependencies = ["extract_raw_qa_1"]
        context_scope = {
            "observe": ["extract_raw_qa_"]  # Field prefix pattern = wildcard
        }

        allowed_fields = _extract_allowed_fields_per_dependency(
            dependencies, context_scope, action_name="test_action"
        )

        # Field prefix pattern means all fields (None)
        assert allowed_fields["extract_raw_qa_1"] is None

    def test_mixed_loop_and_regular_dependencies(self):
        """Test validation with both loop and regular dependencies."""
        dependencies = ["loop_1", "loop_2", "regular_action"]
        context_scope = {
            "observe": ["loop_", "regular_action.field1"]  # Mixed patterns
        }

        allowed_fields = _extract_allowed_fields_per_dependency(
            dependencies, context_scope, action_name="consumer"
        )

        # Loop iterations covered by field prefix pattern
        assert allowed_fields["loop_1"] is None
        assert allowed_fields["loop_2"] is None
        # Regular action has specific field
        assert allowed_fields["regular_action"] == ["field1"]

    def test_extract_action_names_with_field_prefix_pattern(self):
        """Test that field prefix patterns are recognized in action name extraction."""
        context_scope = {
            "observe": ["extract_raw_qa_", "regular_action.field1"],
            "passthrough": ["other_action.*"],
        }

        action_names = extract_action_names_from_context_scope(context_scope)

        # All action names should be extracted, including from field prefix pattern
        assert action_names == {"extract_raw_qa", "regular_action", "other_action"}


class TestFieldPrefixPatternInInferDependencies:
    """Test field prefix pattern handling in infer_dependencies."""

    def test_infer_dependencies_with_field_prefix_pattern(self):
        """Test that field prefix patterns work in dependency inference."""
        # After orchestration expansion
        action_config = {
            "dependencies": ["extract_raw_qa_1", "extract_raw_qa_2"],
            "context_scope": {
                "observe": ["extract_raw_qa_"]  # Field prefix pattern covers all
            },
        }
        workflow_actions = ["extract_raw_qa_1", "extract_raw_qa_2", "flatten_questions"]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "flatten_questions"
        )

        # All loop iterations should be input sources
        assert set(input_sources) == {"extract_raw_qa_1", "extract_raw_qa_2"}
        # No context sources (all in dependencies)
        assert context_sources == []

    def test_normalized_wildcard_context_scope_covers_versioned_dependencies(self):
        """Normalized wildcard context_scope matches versioned dependency names."""
        dependencies = [
            "validate_answer_from_source_1",
            "validate_answer_from_source_2",
            "validate_answer_from_source_3",
        ]
        # Normalized form (what normalizer produces from "validate_answer_from_source.*")
        context_scope = {"observe": ["validate_answer_from_source_"]}

        allowed = _extract_allowed_fields_per_dependency(
            dependencies, context_scope, action_name="aggregate_validation_votes"
        )

        assert allowed["validate_answer_from_source_1"] is None
        assert allowed["validate_answer_from_source_2"] is None
        assert allowed["validate_answer_from_source_3"] is None

    def test_infer_dependencies_with_mixed_patterns(self):
        """Test dependency inference with both field prefix and regular patterns."""
        action_config = {
            "dependencies": ["loop_1", "loop_2"],
            "context_scope": {
                "observe": ["loop_", "context_action.field1"]  # Mixed
            },
        }
        workflow_actions = ["loop_1", "loop_2", "context_action", "consumer"]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "consumer"
        )

        assert set(input_sources) == {"loop_1", "loop_2"}
        assert context_sources == ["context_action"]
