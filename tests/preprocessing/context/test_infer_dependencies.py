"""
Tests for the infer_dependencies() method in ContextScopeProcessor.

Tests the auto-inference of input sources vs context sources from
action configuration and context_scope declarations.
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_builder import build_field_context_with_history
from agent_actions.prompt.context.scope_inference import infer_dependencies
from agent_actions.prompt.context.scope_parsing import extract_action_names_from_context_scope


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

        result = extract_action_names_from_context_scope(context_scope)

        assert result == {"add_answer_text", "suggest_distractor_counts", "write_scenario_question"}

    def test_extracts_action_names_from_passthrough(self):
        """Test extraction from passthrough fields."""
        context_scope = {"passthrough": ["action_A.field1", "action_B.field2"]}

        result = extract_action_names_from_context_scope(context_scope)

        assert result == {"action_A", "action_B"}

    def test_combines_observe_and_passthrough(self):
        """Test that both observe and passthrough are combined."""
        context_scope = {
            "observe": ["action_A.*"],
            "passthrough": ["action_B.field1", "action_C.field2"],
        }

        result = extract_action_names_from_context_scope(context_scope)

        assert result == {"action_A", "action_B", "action_C"}

    def test_deduplicates_action_names(self):
        """Test that same action referenced multiple times is deduplicated."""
        context_scope = {"observe": ["action_A.field1", "action_A.field2", "action_A.*"]}

        result = extract_action_names_from_context_scope(context_scope)

        assert result == {"action_A"}

    def test_empty_context_scope_returns_empty_set(self):
        """Test with empty context_scope."""
        assert extract_action_names_from_context_scope({}) == set()
        assert extract_action_names_from_context_scope(None) == set()

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

        result = extract_action_names_from_context_scope(context_scope)

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

        input_sources, context_sources = infer_dependencies(
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

        input_sources, context_sources = infer_dependencies(
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

        input_sources, context_sources = infer_dependencies(action_config, workflow_actions, "test")

        assert input_sources == ["action_A"]
        assert context_sources == ["action_B"]

    def test_no_dependencies_only_context(self):
        """Test action with no dependencies, only context references."""
        action_config = {"dependencies": None, "context_scope": {"observe": ["action_A.*"]}}
        workflow_actions = ["action_A", "test_action"]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "test_action"
        )

        assert input_sources == []
        assert context_sources == ["action_A"]

    def test_empty_dependencies(self):
        """Test with empty dependencies list."""
        action_config = {"dependencies": [], "context_scope": {"observe": ["action_A.*"]}}
        workflow_actions = ["action_A"]

        input_sources, context_sources = infer_dependencies(action_config, workflow_actions, "test")

        assert input_sources == []
        assert context_sources == ["action_A"]

    def test_no_context_scope(self):
        """Test with dependencies but no context_scope."""
        action_config = {"dependencies": "action_A"}
        workflow_actions = ["action_A"]

        input_sources, context_sources = infer_dependencies(action_config, workflow_actions, "test")

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
            infer_dependencies(action_config, workflow_actions, "test_action")

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
            infer_dependencies(action_config, workflow_actions, "test_action")

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

        input_sources, context_sources = infer_dependencies(
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

        input_sources, context_sources = infer_dependencies(
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
            build_field_context_with_history(
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
        result = build_field_context_with_history(
            agent_name="test_action",
            agent_config=agent_config,
            agent_indices=None,
        )

        assert isinstance(result, dict)


class TestLoopBaseNameExpansion:
    """Test automatic expansion of loop base names in dependencies and context_scope."""

    def test_version_base_name_in_dependencies_expands_to_variants(self):
        """When dependencies references a loop base name, it should expand to all variants."""
        action_config = {
            "dependencies": ["extract_raw_qa"],  # Loop base name
        }
        workflow_actions = [
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "extract_raw_qa_3",
            "flatten_questions",
        ]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "flatten_questions"
        )

        # Should expand to all loop variants
        assert set(input_sources) == {"extract_raw_qa_1", "extract_raw_qa_2", "extract_raw_qa_3"}
        assert context_sources == []

    def test_version_base_name_in_context_scope_expands_to_variants(self):
        """When context_scope references a loop base name, it should expand to all variants."""
        action_config = {
            "dependencies": ["other_action"],
            "context_scope": {
                "observe": [
                    "extract_raw_qa.field1",  # Loop base name
                    "other_action.field2",
                ]
            },
        }
        workflow_actions = [
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "extract_raw_qa_3",
            "other_action",
            "flatten_questions",
        ]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "flatten_questions"
        )

        # dependencies should expand
        assert input_sources == ["other_action"]
        # context_scope should expand loop base name
        assert set(context_sources) == {"extract_raw_qa_1", "extract_raw_qa_2", "extract_raw_qa_3"}

    def test_loop_consumption_pattern_with_context_scope(self):
        """Test the common loop_consumption pattern where both deps and context reference loop."""
        action_config = {
            "dependencies": ["extract_raw_qa"],
            "loop_consumption": {
                "source": "extract_raw_qa",
                "pattern": "merge",
            },
            "context_scope": {"observe": ["extract_raw_qa.*"]},
        }
        workflow_actions = [
            "extract_raw_qa_1",
            "extract_raw_qa_2",
            "extract_raw_qa_3",
            "flatten_questions",
        ]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "flatten_questions"
        )

        # Both should expand to all variants
        # Note: extract_raw_qa is in BOTH deps and context_scope
        # So after expansion, all variants are input_sources (since they're in dependencies)
        assert set(input_sources) == {"extract_raw_qa_1", "extract_raw_qa_2", "extract_raw_qa_3"}
        # Context sources are auto-inferred: actions in context_scope but NOT in dependencies
        # Since extract_raw_qa is in both, after expansion all variants are in input_sources
        # So context_sources should be empty
        assert context_sources == []

    def test_mixed_loop_and_regular_actions(self):
        """Test expansion when both loop and regular actions are referenced."""
        action_config = {
            "dependencies": ["regular_action"],
            "context_scope": {
                "observe": [
                    "loop_action.field1",
                    "regular_action.field2",
                ]
            },
        }
        workflow_actions = [
            "loop_action_1",
            "loop_action_2",
            "regular_action",
            "consumer",
        ]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "consumer"
        )

        # Regular action stays as-is
        assert input_sources == ["regular_action"]
        # Loop action expands
        assert set(context_sources) == {"loop_action_1", "loop_action_2"}


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

        input_sources, context_sources = infer_dependencies(action_config, workflow_actions, "test")

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

        input_sources, context_sources = infer_dependencies(action_config, workflow_actions, "test")

        assert input_sources == ["action_A"]
        assert context_sources == ["action_B"]  # Only one entry, not duplicated


class TestInferDependenciesFourPatterns:
    """
    Test infer_dependencies() for all 4 dependency patterns.

    Patterns:
    1. Single - One dependency, output becomes input
    2. Parallel Branches - Same base name (classify_1, classify_2), all merged
    3. Fan-in - Different actions, first is primary, others via context
    4. Aggregation - Different actions with reduce_key, all merged
    """

    def test_pattern_1_single_dependency(self):
        """Pattern 1: Single dependency - output becomes input."""
        action_config = {
            "dependencies": "extract_data",
            "context_scope": {"observe": ["extract_data.*"]},
        }
        workflow_actions = ["extract_data", "validate_data"]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "validate_data"
        )

        assert input_sources == ["extract_data"]
        assert context_sources == []  # Single dep is input, nothing extra in context

    def test_pattern_2_parallel_branches_all_inputs(self):
        """Pattern 2: Parallel branches - all become input sources (merged)."""
        action_config = {
            "dependencies": ["classify_1", "classify_2", "classify_3"],
            "context_scope": {"observe": ["classify_1.*", "classify_2.*", "classify_3.*"]},
        }
        workflow_actions = ["classify_1", "classify_2", "classify_3", "synthesize"]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "synthesize"
        )

        # All parallel branches are input sources (merged for execution)
        assert set(input_sources) == {"classify_1", "classify_2", "classify_3"}
        assert context_sources == []  # All are already inputs

    def test_pattern_3_fan_in_first_is_primary(self):
        """Pattern 3: Fan-in - first dependency is primary, rest become context."""
        action_config = {
            "dependencies": ["analyze_sentiment", "analyze_entities", "analyze_topics"],
            "context_scope": {
                "observe": [
                    "analyze_sentiment.*",
                    "analyze_entities.*",
                    "analyze_topics.*",
                ]
            },
        }
        workflow_actions = [
            "analyze_sentiment",
            "analyze_entities",
            "analyze_topics",
            "generate_report",
        ]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "generate_report"
        )

        # Fan-in: first dep is primary input, rest are context sources
        assert input_sources == ["analyze_sentiment"]
        assert set(context_sources) == {"analyze_entities", "analyze_topics"}

    def test_pattern_3_fan_in_with_primary_override(self):
        """Pattern 3: Fan-in with primary_dependency override."""
        action_config = {
            "dependencies": ["analyze_sentiment", "analyze_entities", "analyze_topics"],
            "primary_dependency": "analyze_entities",  # Override: entities is primary
            "context_scope": {
                "observe": [
                    "analyze_sentiment.*",
                    "analyze_entities.*",
                    "analyze_topics.*",
                ]
            },
        }
        workflow_actions = [
            "analyze_sentiment",
            "analyze_entities",
            "analyze_topics",
            "generate_report",
        ]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "generate_report"
        )

        # Primary override: analyze_entities is input, rest are context
        assert input_sources == ["analyze_entities"]
        assert set(context_sources) == {"analyze_sentiment", "analyze_topics"}

    def test_pattern_4_aggregation_all_inputs(self):
        """Pattern 4: Aggregation with reduce_key - all become input sources."""
        action_config = {
            "dependencies": ["validator_grammar", "validator_accuracy", "validator_style"],
            "reduce_key": "content_id",  # Aggregation pattern
            "context_scope": {
                "observe": [
                    "validator_grammar.*",
                    "validator_accuracy.*",
                    "validator_style.*",
                ]
            },
        }
        workflow_actions = [
            "validator_grammar",
            "validator_accuracy",
            "validator_style",
            "aggregate_validations",
        ]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "aggregate_validations"
        )

        # Aggregation: all dependencies are input sources (merged and grouped)
        assert set(input_sources) == {
            "validator_grammar",
            "validator_accuracy",
            "validator_style",
        }
        assert context_sources == []  # All are already inputs

    def test_versioned_primary_expands_to_all_branches(self):
        """Versioned primary: research_1, research_2, research_3 + summarize."""
        action_config = {
            "dependencies": ["research_1", "research_2", "research_3", "summarize"],
            "context_scope": {
                "observe": [
                    "research_1.*",
                    "research_2.*",
                    "research_3.*",
                    "summarize.*",
                ]
            },
        }
        workflow_actions = [
            "research_1",
            "research_2",
            "research_3",
            "summarize",
            "final_report",
        ]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "final_report"
        )

        # Versioned primary: all research branches become inputs, summarize is context
        assert set(input_sources) == {"research_1", "research_2", "research_3"}
        assert context_sources == ["summarize"]

    def test_versioned_primary_with_base_name_override(self):
        """primary_dependency as base name expands to all version branches."""
        action_config = {
            "dependencies": ["research_1", "research_2", "summarize"],
            "primary_dependency": "research",  # Base name, not in list directly
            "context_scope": {"observe": ["research_1.*", "research_2.*", "summarize.*"]},
        }
        workflow_actions = ["research_1", "research_2", "summarize", "final_report"]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "final_report"
        )

        # Base name expands to all matching version branches
        assert set(input_sources) == {"research_1", "research_2"}
        assert context_sources == ["summarize"]

    def test_different_base_names_with_same_suffix_is_fan_in(self):
        """Different base names with same numeric suffix → fan-in, not parallel."""
        action_config = {
            "dependencies": ["classify_text_1", "classify_image_1"],
            "context_scope": {"observe": ["classify_text_1.*", "classify_image_1.*"]},
        }
        workflow_actions = ["classify_text_1", "classify_image_1", "combine"]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "combine"
        )

        # Fan-in: first is primary (classify_text_1), second is context
        assert input_sources == ["classify_text_1"]
        assert context_sources == ["classify_image_1"]

    def test_reduce_key_with_parallel_branches(self):
        """reduce_key with parallel branches - all become inputs (merge + group)."""
        action_config = {
            "dependencies": ["classify_1", "classify_2", "classify_3"],
            "reduce_key": "content_id",
            "context_scope": {"observe": ["classify_1.*", "classify_2.*", "classify_3.*"]},
        }
        workflow_actions = ["classify_1", "classify_2", "classify_3", "aggregate"]

        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "aggregate"
        )

        # reduce_key overrides: all are inputs regardless of pattern
        assert set(input_sources) == {"classify_1", "classify_2", "classify_3"}
        assert context_sources == []
