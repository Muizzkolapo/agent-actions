"""Tests for configuration hierarchy resolution (project → workflow → action)."""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.output.response.expander import ActionExpander
from agent_actions.utils.constants import HITL_OUTPUT_JSON_SCHEMA, HITL_OUTPUT_SCHEMA

HIERARCHY_CASES = [
    pytest.param(
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "PROJECT_KEY"},
        {"name": "test_action", "intent": "Test action with no overrides"},
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "PROJECT_KEY"},
        id="project_only",
    ),
    pytest.param(
        {"model_vendor": "anthropic", "model_name": "claude-3-5-sonnet", "api_key": "PROJECT_KEY"},
        {"name": "test_action", "intent": "Test"},
        {"model_vendor": "anthropic", "model_name": "claude-3-5-sonnet", "api_key": "PROJECT_KEY"},
        id="workflow_overrides",
    ),
    pytest.param(
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "DEFAULT_KEY"},
        {
            "name": "test_action",
            "intent": "Test",
            "model_vendor": "anthropic",
            "model_name": "claude-3-5-sonnet",
        },
        {"model_vendor": "anthropic", "model_name": "claude-3-5-sonnet", "api_key": "DEFAULT_KEY"},
        id="action_overrides_all",
    ),
    pytest.param(
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "DEFAULT_KEY"},
        {"name": "test_action", "intent": "Test", "model_name": "gpt-4o-mini"},
        {"model_vendor": "openai", "model_name": "gpt-4o-mini", "api_key": "DEFAULT_KEY"},
        id="partial_overrides",
    ),
    pytest.param(
        {"model_vendor": "openai", "api_key": "PROJECT_KEY"},
        {"name": "test_action", "intent": "Test", "model_name": "gpt-4o-mini"},
        {"model_vendor": "openai", "model_name": "gpt-4o-mini", "api_key": "PROJECT_KEY"},
        id="three_levels_different_fields",
    ),
    pytest.param(
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "DEFAULT_KEY"},
        {"name": "test_action", "intent": "Test"},
        {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "DEFAULT_KEY"},
        id="missing_fields_use_defaults",
    ),
    pytest.param(
        {},
        {
            "name": "test_action",
            "intent": "Test",
            "model_vendor": "anthropic",
            "model_name": "claude-3-5-sonnet",
            "api_key": "ACTION_KEY",
        },
        {"model_vendor": "anthropic", "model_name": "claude-3-5-sonnet", "api_key": "ACTION_KEY"},
        id="empty_defaults_with_action_values",
    ),
]


class TestActionExpanderHierarchy:
    """Test 3-level configuration hierarchy resolution."""

    @pytest.mark.parametrize("defaults,action,expected", HIERARCHY_CASES)
    def test_config_hierarchy(self, defaults, action, expected):
        """Test that configuration hierarchy resolves correctly."""
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        for key, value in expected.items():
            assert result[key] == value, f"Field '{key}': expected {value!r}, got {result[key]!r}"

    def test_other_fields_inherit_correctly(self):
        """Test that other fields like json_mode inherit properly."""
        defaults = {
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "api_key": "DEFAULT_KEY",
            "json_mode": True,
            "granularity": "record",
        }
        action = {"name": "test_action", "intent": "Test"}
        agent = {"agent_type": "test_action", "name": "test_action"}
        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["model_vendor"] == "openai"
        assert result["model_name"] == "gpt-4"
        assert result.get("json_mode") == True
        assert result.get("granularity") == "Record"


class TestJudgeContextAutoInjection:
    """A judged expectation's context: refs must reach the action's own
    context_scope.observe, or the framework's dependency inference never
    picks up the referenced action and the data never reaches llm_context."""

    @staticmethod
    def _agent_for(expect, context_scope=None):
        action = {"name": "brainstorm", "intent": "Test", "expect": expect}
        if context_scope is not None:
            action["context_scope"] = context_scope
        agent = {"agent_type": "brainstorm", "name": "brainstorm"}
        defaults = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "KEY"}
        return ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)

    def test_context_ref_is_unioned_into_existing_observe(self):
        expect = {
            "repair": "none",
            "expectations": [
                {
                    "id": "on_topic",
                    "type": "llm_judge",
                    "field": "ideas",
                    "rule": "on topic",
                    "context": ["extract_context.source_context"],
                }
            ],
        }
        agent = self._agent_for(expect, context_scope={"observe": ["source.*"]})
        assert "extract_context.source_context" in agent["context_scope"]["observe"]
        assert "source.*" in agent["context_scope"]["observe"]

    def test_no_context_scope_declared_still_gets_one_from_context_refs(self):
        expect = {
            "repair": "none",
            "expectations": [
                {
                    "id": "on_topic",
                    "type": "llm_judge",
                    "field": "ideas",
                    "rule": "on topic",
                    "context": ["extract_context.source_context"],
                }
            ],
        }
        agent = self._agent_for(expect)
        assert agent["context_scope"]["observe"] == ["extract_context.source_context"]

    def test_duplicate_ref_is_not_added_twice(self):
        expect = {
            "repair": "none",
            "expectations": [
                {
                    "id": "on_topic",
                    "type": "llm_judge",
                    "field": "ideas",
                    "rule": "on topic",
                    "context": ["extract_context.source_context"],
                }
            ],
        }
        agent = self._agent_for(
            expect, context_scope={"observe": ["extract_context.source_context"]}
        )
        assert agent["context_scope"]["observe"].count("extract_context.source_context") == 1

    def test_non_judge_expectations_do_not_affect_observe(self):
        expect = {
            "repair": "none",
            "expectations": [{"id": "nn", "type": "not_null", "field": "ideas"}],
        }
        agent = self._agent_for(expect, context_scope={"observe": ["source.*"]})
        assert agent["context_scope"]["observe"] == ["source.*"]

    def test_no_expect_block_leaves_context_scope_untouched(self):
        agent = self._agent_for(expect=None, context_scope={"observe": ["source.*"]})
        assert agent["context_scope"]["observe"] == ["source.*"]

    def test_multiple_judge_expectations_union_all_refs(self):
        expect = {
            "repair": "none",
            "expectations": [
                {
                    "id": "a",
                    "type": "llm_judge",
                    "field": "ideas",
                    "rule": "r1",
                    "context": ["extract_context.source_context"],
                },
                {
                    "id": "b",
                    "type": "llm_judge",
                    "field": "ideas",
                    "rule": "r2",
                    "context": ["another_action.other_field"],
                },
            ],
        }
        agent = self._agent_for(expect)
        assert set(agent["context_scope"]["observe"]) == {
            "extract_context.source_context",
            "another_action.other_field",
        }


class TestOutputSchemaContract:
    """Test uniform output schema across all action types."""

    # -- Helpers --

    @staticmethod
    def _make_hitl_action(name="review"):
        return {
            "name": name,
            "intent": "Human review",
            "kind": "hitl",
            "hitl": {"instructions": "Please review"},
        }

    @staticmethod
    def _make_tool_action(name="my_tool", impl="mod.func", schema=None):
        action = {"name": name, "intent": "Run tool", "kind": "tool", "impl": impl}
        if schema is not None:
            action["schema"] = schema
        return action

    @staticmethod
    def _make_llm_action(name="summarize", schema=None):
        action = {
            "name": name,
            "intent": "Summarize",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "api_key": "KEY",
        }
        if schema is not None:
            action["schema"] = schema
        return action

    @staticmethod
    def _expand_single(action, defaults=None):
        defaults = defaults or {}
        agent = {"agent_type": action["name"], "name": action["name"]}
        return ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)

    # -- HITL tests --

    def test_hitl_action_gets_auto_injected_schema(self):
        """HITL actions receive json_output_schema with hitl_status, user_comment, timestamp."""
        result = self._expand_single(self._make_hitl_action())

        assert result.get("output_schema") == HITL_OUTPUT_SCHEMA
        assert result.get("json_output_schema") == HITL_OUTPUT_JSON_SCHEMA

    def test_hitl_record_granularity_raises(self):
        """HITL action with granularity: record raises ConfigurationError at expansion."""
        action = self._make_hitl_action()
        action["granularity"] = "record"
        with pytest.raises(ConfigurationError, match="HITL actions require FILE granularity"):
            self._expand_single(action)

    # -- Tool tests --

    def test_tool_yaml_schema_compiled_to_json_output_schema(self):
        """Tool with YAML schema: gets json_output_schema."""
        schema = [
            {"id": "correct_answer_words", "type": "string"},
            {"id": "score", "type": "number"},
        ]
        result = self._expand_single(self._make_tool_action(schema=schema))

        assert result.get("json_output_schema") is not None
        props = result["json_output_schema"]["properties"]
        assert "correct_answer_words" in props
        assert "score" in props

    def test_tool_no_schema_raises_error(self):
        """Tool with no schema at all raises ConfigValidationError."""
        from agent_actions.errors import ConfigValidationError

        with pytest.raises(ConfigValidationError, match="no output schema"):
            self._expand_single(self._make_tool_action(schema=None))

    # -- LLM tests --

    def test_llm_schema_compilation_unchanged(self):
        """LLM actions with YAML schema still get json_output_schema."""
        schema = [
            {"id": "summary", "type": "string"},
            {"id": "confidence", "type": "number"},
        ]
        result = self._expand_single(self._make_llm_action(schema=schema))

        assert result.get("json_output_schema") is not None
        props = result["json_output_schema"]["properties"]
        assert "summary" in props
        assert "confidence" in props

    def test_llm_without_schema_has_no_json_output_schema(self):
        """LLM actions without YAML schema: have no json_output_schema."""
        result = self._expand_single(self._make_llm_action(schema=None))
        assert result.get("json_output_schema") is None
