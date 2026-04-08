"""
Tests for version base name expansion in context_scope.

After early normalization, version base name references (e.g., "action.*")
are expanded to concrete versioned references (e.g., "action_1.*", "action_2.*").
Downstream code only sees standard action.field or action.* patterns.
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_inference import infer_dependencies
from agent_actions.prompt.context.scope_namespace import _extract_allowed_fields_per_dependency
from agent_actions.prompt.context.scope_parsing import (
    extract_action_names_from_context_scope,
    parse_field_reference,
)


class TestFieldReferenceParsing:
    """Test that parse_field_reference handles standard patterns only."""

    def test_parse_dotted_reference(self):
        action_name, field_name = parse_field_reference("action_1.field")
        assert action_name == "action_1"
        assert field_name == "field"

    def test_parse_wildcard_reference(self):
        action_name, field_name = parse_field_reference("action_1.*")
        assert action_name == "action_1"
        assert field_name == "*"

    def test_no_dot_raises(self):
        with pytest.raises(ValueError, match="Expected format"):
            parse_field_reference("nodot")

    def test_trailing_underscore_no_dot_raises(self):
        """After redesign, trailing underscore without dot is invalid."""
        with pytest.raises(ValueError, match="Expected format"):
            parse_field_reference("action_")


class TestExpandedVersionDependencyValidation:
    """Test that concrete versioned refs work with dependency validation."""

    def test_concrete_versioned_wildcards_cover_deps(self):
        """Post-normalization: action_1.*, action_2.* cover deps action_1, action_2."""
        dependencies = ["extract_raw_qa_1", "extract_raw_qa_2", "extract_raw_qa_3"]
        context_scope = {
            "observe": [
                "extract_raw_qa_1.*",
                "extract_raw_qa_2.*",
                "extract_raw_qa_3.*",
            ]
        }

        allowed_fields = _extract_allowed_fields_per_dependency(
            dependencies, context_scope, action_name="flatten_questions"
        )

        assert allowed_fields["extract_raw_qa_1"] is None
        assert allowed_fields["extract_raw_qa_2"] is None
        assert allowed_fields["extract_raw_qa_3"] is None

    def test_missing_version_ref_raises(self):
        """If a versioned dep has no matching context_scope entry, it errors."""
        dependencies = ["extract_raw_qa_1"]
        context_scope = {"observe": ["other_action.*"]}

        with pytest.raises(
            ConfigurationError, match="Dependency 'extract_raw_qa_1' declared but not referenced"
        ):
            _extract_allowed_fields_per_dependency(
                dependencies, context_scope, action_name="test_action"
            )

    def test_concrete_specific_fields_cover_deps(self):
        """Post-normalization: action_1.score covers dep action_1 with specific field."""
        dependencies = ["action_1", "action_2"]
        context_scope = {"observe": ["action_1.score", "action_2.score"]}

        allowed_fields = _extract_allowed_fields_per_dependency(
            dependencies, context_scope, action_name="consumer"
        )

        assert allowed_fields["action_1"] == ["score"]
        assert allowed_fields["action_2"] == ["score"]

    def test_mixed_versioned_and_regular_deps(self):
        dependencies = ["loop_1", "loop_2", "regular_action"]
        context_scope = {"observe": ["loop_1.*", "loop_2.*", "regular_action.field1"]}

        allowed_fields = _extract_allowed_fields_per_dependency(
            dependencies, context_scope, action_name="consumer"
        )

        assert allowed_fields["loop_1"] is None
        assert allowed_fields["loop_2"] is None
        assert allowed_fields["regular_action"] == ["field1"]

    def test_extract_action_names_from_concrete_refs(self):
        context_scope = {
            "observe": ["action_1.*", "action_2.*", "regular.field1"],
            "passthrough": ["other.*"],
        }

        action_names = extract_action_names_from_context_scope(context_scope)

        assert action_names == {"action_1", "action_2", "regular", "other"}


class TestInferDependenciesWithConcreteRefs:
    """Test dependency inference with post-normalization concrete refs."""

    def test_infer_dependencies_with_concrete_versioned_refs(self):
        action_config = {
            "dependencies": ["extract_raw_qa_1", "extract_raw_qa_2"],
            "context_scope": {"observe": ["extract_raw_qa_1.*", "extract_raw_qa_2.*"]},
        }
        workflow_actions = ["extract_raw_qa_1", "extract_raw_qa_2", "flatten_questions"]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "flatten_questions"
        )

        assert set(input_sources) == {"extract_raw_qa_1", "extract_raw_qa_2"}
        assert context_sources == []

    def test_infer_dependencies_with_mixed_patterns(self):
        action_config = {
            "dependencies": ["loop_1", "loop_2"],
            "context_scope": {"observe": ["loop_1.*", "loop_2.*", "context_action.field1"]},
        }
        workflow_actions = ["loop_1", "loop_2", "context_action", "consumer"]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "consumer"
        )

        assert set(input_sources) == {"loop_1", "loop_2"}
        assert context_sources == ["context_action"]
