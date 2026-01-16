"""
Tests for the infer_dependencies() method in ContextScopeProcessor.

Tests the auto-inference of input sources vs context sources from
action configuration and context_scope declarations.
"""

import pytest
from agent_actions.preprocessing.context.context_scope_processor import ContextScopeProcessor
from agent_actions.errors import ConfigurationError


class TestExtractActionNamesFromContextScope:
    """Test extract_action_names_from_context_scope() helper method."""

    def test_extracts_action_names_from_observe(self):
        """Test extraction from observe fields."""
        context_scope = {
            "observe": [
                "add_answer_text.*",
                "suggest_distractor_counts.target_word_counts",
                "write_scenario_question.question",
            ]
        }

        result = ContextScopeProcessor.extract_action_names_from_context_scope(context_scope)

        assert result == {"add_answer_text", "suggest_distractor_counts", "write_scenario_question"}

    def test_extracts_action_names_from_passthrough(self):
        """Test extraction from passthrough fields."""
        context_scope = {"passthrough": ["action_A.field1", "action_B.field2"]}

        result = ContextScopeProcessor.extract_action_names_from_context_scope(context_scope)

        assert result == {"action_A", "action_B"}

    def test_combines_observe_and_passthrough(self):
        """Test that both observe and passthrough are combined."""
        context_scope = {
            "observe": ["action_A.*"],
            "passthrough": ["action_B.field1", "action_C.field2"],
        }

        result = ContextScopeProcessor.extract_action_names_from_context_scope(context_scope)

        assert result == {"action_A", "action_B", "action_C"}

    def test_deduplicates_action_names(self):
        """Test that same action referenced multiple times is deduplicated."""
        context_scope = {"observe": ["action_A.field1", "action_A.field2", "action_A.*"]}

        result = ContextScopeProcessor.extract_action_names_from_context_scope(context_scope)

        assert result == {"action_A"}

    def test_empty_context_scope_returns_empty_set(self):
        """Test with empty context_scope."""
        assert ContextScopeProcessor.extract_action_names_from_context_scope({}) == set()
        assert ContextScopeProcessor.extract_action_names_from_context_scope(None) == set()

    def test_ignores_invalid_references(self):
        """Test that invalid field references are skipped."""
        context_scope = {
            "observe": [
                "valid_action.field",
                "invalid_no_dot",  # Invalid: no dot
                "",  # Invalid: empty
                "also_valid.field2",
            ]
        }

        result = ContextScopeProcessor.extract_action_names_from_context_scope(context_scope)

        assert result == {"valid_action", "also_valid"}


class TestInferDependencies:
    """Test infer_dependencies() method."""

    def test_single_input_with_context_deps(self):
        """Test single input source with auto-inferred context dependencies."""
        action_config = {
            "dependencies": "add_answer_text",
            "context_scope": {
                "observe": [
                    "add_answer_text.*",
                    "suggest_distractor_counts.*",
                    "write_scenario_question.question",
                ]
            },
        }
        workflow_actions = [
            "extract",
            "flatten",
            "add_answer_text",
            "suggest_distractor_counts",
            "write_scenario_question",
        ]

        input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
            action_config, workflow_actions, "test_action"
        )

        assert input_sources == ["add_answer_text"]
        assert set(context_sources) == {"suggest_distractor_counts", "write_scenario_question"}

    def test_multiple_inputs_no_context(self):
        """Test multiple input sources with no context dependencies."""
        action_config = {
            "dependencies": ["validate_1", "validate_2", "validate_3"],
            "context_scope": {"observe": ["validate_1.*", "validate_2.*", "validate_3.*"]},
        }
        workflow_actions = ["validate_1", "validate_2", "validate_3", "aggregate"]

        input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
            action_config, workflow_actions, "aggregate"
        )

        assert set(input_sources) == {"validate_1", "validate_2", "validate_3"}
        assert context_sources == []  # All are input sources

    def test_dependencies_as_list_single_item(self):
        """Test dependencies as single-item list."""
        action_config = {
            "dependencies": ["action_A"],
            "context_scope": {"observe": ["action_A.*", "action_B.*"]},
        }
        workflow_actions = ["action_A", "action_B"]

        input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
            action_config, workflow_actions, "test"
        )

        assert input_sources == ["action_A"]
        assert context_sources == ["action_B"]

    def test_no_dependencies_only_context(self):
        """Test action with no dependencies, only context references."""
        action_config = {"dependencies": None, "context_scope": {"observe": ["action_A.*"]}}
        workflow_actions = ["action_A", "test_action"]

        input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
            action_config, workflow_actions, "test_action"
        )

        assert input_sources == []
        assert context_sources == ["action_A"]

    def test_empty_dependencies(self):
        """Test with empty dependencies list."""
        action_config = {"dependencies": [], "context_scope": {"observe": ["action_A.*"]}}
        workflow_actions = ["action_A"]

        input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
            action_config, workflow_actions, "test"
        )

        assert input_sources == []
        assert context_sources == ["action_A"]

    def test_no_context_scope(self):
        """Test with dependencies but no context_scope."""
        action_config = {"dependencies": "action_A"}
        workflow_actions = ["action_A"]

        input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
            action_config, workflow_actions, "test"
        )

        assert input_sources == ["action_A"]
        assert context_sources == []  # Nothing in context_scope to infer

    def test_invalid_action_reference_raises_error(self):
        """Test that referencing non-existent action raises ConfigurationError."""
        action_config = {
            "dependencies": "action_A",
            "context_scope": {
                "observe": [
                    "action_A.*",
                    "nonexistent_action.field",  # Not in workflow
                ]
            },
        }
        workflow_actions = ["action_A"]  # nonexistent_action not here

        with pytest.raises(ConfigurationError) as exc_info:
            ContextScopeProcessor.infer_dependencies(action_config, workflow_actions, "test_action")

        assert "nonexistent_action" in str(exc_info.value)
        assert "not found in workflow" in str(exc_info.value)

    def test_invalid_input_dependency_raises_error(self):
        """Test that invalid input dependency raises ConfigurationError."""
        action_config = {
            "dependencies": "nonexistent_input",  # Not in workflow
            "context_scope": {"observe": ["nonexistent_input.*"]},
        }
        workflow_actions = ["action_A", "action_B"]

        with pytest.raises(ConfigurationError) as exc_info:
            ContextScopeProcessor.infer_dependencies(action_config, workflow_actions, "test_action")

        assert "nonexistent_input" in str(exc_info.value)

    def test_real_world_generate_distractor_example(self):
        """Test with real-world generate_distractor_1 config."""
        action_config = {
            "dependencies": ["add_answer_text"],
            "context_scope": {
                "observe": [
                    "suggest_distractor_counts.*",
                    "add_answer_text.target_word_counts",
                    "add_answer_text.answer_text",
                    "write_scenario_question.question",
                    "write_scenario_question.options",
                    "write_scenario_question.answer",
                    "write_scenario_question.answer_explanation",
                ]
            },
        }
        workflow_actions = [
            "extract_raw_qa",
            "flatten_raw_questions",
            "classify_question_type",
            "get_authoring_prompt",
            "write_scenario_question",
            "fix_options_format",
            "suggest_distractor_counts",
            "add_answer_text",
            "generate_distractor_1",
        ]

        input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
            action_config, workflow_actions, "generate_distractor_1"
        )

        assert input_sources == ["add_answer_text"]
        assert set(context_sources) == {"suggest_distractor_counts", "write_scenario_question"}

    def test_real_world_write_scenario_question_example(self):
        """Test with real-world write_scenario_question config (single input + context)."""
        action_config = {
            "dependencies": ["get_authoring_prompt"],  # Single input source
            "context_scope": {
                "observe": [
                    "flatten_raw_questions.question_text",
                    "flatten_raw_questions.answer_text",
                    "flatten_raw_questions.source_quote",
                    "flatten_raw_questions.difficulty_reason",
                    "classify_question_type.quiz_type",
                    "get_authoring_prompt.authoring_prompt",
                    "get_authoring_prompt.suggested_opener",
                ]
            },
        }
        workflow_actions = [
            "extract_raw_qa",
            "flatten_raw_questions",
            "classify_question_type",
            "get_authoring_prompt",
            "write_scenario_question",
        ]

        input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
            action_config, workflow_actions, "write_scenario_question"
        )

        assert input_sources == ["get_authoring_prompt"]
        assert set(context_sources) == {"flatten_raw_questions", "classify_question_type"}


class TestBuildFieldContextRequiresAgentIndices:
    """Test that build_field_context_with_history requires agent_indices when dependencies exist."""

    def test_raises_error_when_dependencies_without_agent_indices(self):
        """Test that ConfigurationError is raised when dependencies exist but no agent_indices."""
        from agent_actions.errors import ConfigurationError

        agent_config = {"dependencies": ["action_A"], "context_scope": {"observe": ["action_A.*"]}}

        with pytest.raises(ConfigurationError) as exc_info:
            ContextScopeProcessor.build_field_context_with_history(
                contents={},
                agent_name="test_action",
                agent_config=agent_config,
                agent_indices=None,  # No agent_indices!
            )

        assert "agent_indices" in str(exc_info.value)
        assert "required" in str(exc_info.value).lower()

    def test_no_error_when_no_dependencies(self):
        """Test no error when action has no dependencies (agent_indices not needed)."""
        agent_config = {
            # No dependencies
            "context_scope": {}
        }

        # Should not raise - no dependencies means agent_indices not required
        result = ContextScopeProcessor.build_field_context_with_history(
            contents={},
            agent_name="test_action",
            agent_config=agent_config,
            agent_indices=None,
        )

        assert isinstance(result, dict)


class TestInferDependenciesEdgeCases:
    """Test edge cases for infer_dependencies()."""

    def test_passthrough_also_counted(self):
        """Test that passthrough references are also counted as dependencies."""
        action_config = {
            "dependencies": "action_A",
            "context_scope": {
                "observe": ["action_A.*"],
                "passthrough": ["action_B.field1"],  # Only in passthrough
            },
        }
        workflow_actions = ["action_A", "action_B"]

        input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
            action_config, workflow_actions, "test"
        )

        assert input_sources == ["action_A"]
        assert context_sources == ["action_B"]

    def test_same_action_in_observe_and_passthrough(self):
        """Test action referenced in both observe and passthrough is deduplicated."""
        action_config = {
            "dependencies": "action_A",
            "context_scope": {
                "observe": ["action_A.field1", "action_B.field1"],
                "passthrough": ["action_A.field2", "action_B.field2"],
            },
        }
        workflow_actions = ["action_A", "action_B"]

        input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
            action_config, workflow_actions, "test"
        )

        assert input_sources == ["action_A"]
        assert context_sources == ["action_B"]  # Only one entry, not duplicated
