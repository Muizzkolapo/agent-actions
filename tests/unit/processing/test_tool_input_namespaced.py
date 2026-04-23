"""Tests for namespaced content delivery to tools and LLM.

Verifies that after the additive content model (PR #323), tools receive
namespaced dicts directly — no flattening, no fallback to flat format.
"""

from unittest.mock import patch

import pytest

from agent_actions.llm.realtime.services.context import ContextService
from agent_actions.processing.helpers import run_dynamic_agent
from agent_actions.processing.task_preparer import TaskPreparer

# ---------------------------------------------------------------------------
# 1. ContextService — tools receive namespaced data, no flattening
# ---------------------------------------------------------------------------


class TestContextServiceNamespaced:
    """ContextService.prepare_context_data passes namespaced data to tools."""

    def test_tool_receives_namespaced_dict(self):
        """Tool path returns the namespaced dict unchanged — no flatten."""
        namespaced = {"extract": {"text": "hello"}, "classify": {"topic": "science"}}
        result = ContextService.prepare_context_data(namespaced, is_tool=True)
        assert result == namespaced
        assert isinstance(result["extract"], dict)
        assert result["extract"]["text"] == "hello"

    def test_tool_no_collision_same_field_name(self):
        """Two actions with same field name — namespaces keep them separate."""
        namespaced = {
            "extract": {"text": "original"},
            "rewrite": {"text": "rewritten"},
        }
        result = ContextService.prepare_context_data(namespaced, is_tool=True)
        assert result["extract"]["text"] == "original"
        assert result["rewrite"]["text"] == "rewritten"

    def test_tool_version_merge_all_namespaces(self):
        """Version merge: tool receives all version namespaces."""
        namespaced = {
            "score_1": {"score": 8},
            "score_2": {"score": 6},
            "score_3": {"score": 9},
        }
        result = ContextService.prepare_context_data(namespaced, is_tool=True)
        assert len(result) == 3
        assert result["score_1"]["score"] == 8
        assert result["score_2"]["score"] == 6
        assert result["score_3"]["score"] == 9

    def test_tool_string_context_passthrough(self):
        """String context passes through unchanged for tools."""
        result = ContextService.prepare_context_data("raw string", is_tool=True)
        assert result == "raw string"

    def test_tool_empty_dict(self):
        """Empty dict passes through unchanged."""
        result = ContextService.prepare_context_data({}, is_tool=True)
        assert result == {}

    def test_llm_still_json_serializes(self):
        """LLM path still JSON-serializes dicts (unchanged behavior)."""
        namespaced = {"extract": {"text": "hello"}}
        result = ContextService.prepare_context_data(namespaced, is_tool=False)
        assert isinstance(result, str)
        assert '"extract"' in result


# ---------------------------------------------------------------------------
# 2. run_dynamic_agent — no content unwrapping
# ---------------------------------------------------------------------------


class TestRunDynamicAgentNamespaced:
    """run_dynamic_agent passes context directly without unwrapping."""

    @patch("agent_actions.llm.realtime.builder.create_dynamic_agent")
    def test_namespaced_content_passed_directly(self, mock_builder):
        """Namespaced content is passed to the builder without unwrapping."""
        mock_builder.return_value = [{"result": "ok"}]

        namespaced = {"extract": {"text": "hello"}, "classify": {"topic": "sci"}}
        agent_config = {"model_vendor": "tool", "model_name": "my_tool"}

        run_dynamic_agent(
            agent_config,
            "test_action",
            namespaced,
            "prompt text",
            skip_guard_eval=True,
        )

        call_args = mock_builder.call_args
        # context_data_str (positional arg 2) should be the namespaced dict
        assert call_args[0][2] == namespaced

    @patch("agent_actions.llm.realtime.builder.create_dynamic_agent")
    def test_content_key_not_unwrapped(self, mock_builder):
        """Even if an action is named 'content', it is NOT unwrapped."""
        mock_builder.return_value = [{"result": "ok"}]

        # Edge case: action named "content" — should NOT trigger unwrapping
        data = {"content": {"field": "val"}, "other_action": {"x": 1}}
        agent_config = {"model_vendor": "tool", "model_name": "my_tool"}

        run_dynamic_agent(
            agent_config,
            "test_action",
            data,
            "prompt text",
            skip_guard_eval=True,
        )

        call_args = mock_builder.call_args
        # The full dict should be passed, not context["content"]
        assert call_args[0][2] == data

    @patch("agent_actions.llm.realtime.builder.create_dynamic_agent")
    def test_llm_context_takes_precedence(self, mock_builder):
        """When llm_context is provided, it is used as context_data_str."""
        mock_builder.return_value = [{"result": "ok"}]

        original = {"extract": {"text": "hello"}, "classify": {"topic": "sci"}}
        llm_ctx = {"extract": {"text": "hello"}}  # observe-scoped subset (smaller)
        agent_config = {"model_vendor": "openai", "model_name": "gpt-4"}

        run_dynamic_agent(
            agent_config,
            "test_action",
            original,
            "prompt text",
            llm_context=llm_ctx,
            skip_guard_eval=True,
        )

        call_args = mock_builder.call_args
        # llm_context should be used as context_data_str
        assert call_args[0][2] == llm_ctx

    @patch("agent_actions.llm.realtime.builder.create_dynamic_agent")
    def test_file_mode_list_passed_directly(self, mock_builder):
        """File mode: list of records passed through unchanged."""
        mock_builder.return_value = [{"result": "ok"}]

        data = [
            {"content": {"action_a": {"field": "v1"}}, "source_guid": "sg-1"},
            {"content": {"action_a": {"field": "v2"}}, "source_guid": "sg-2"},
        ]
        agent_config = {"model_vendor": "tool", "model_name": "my_tool"}

        run_dynamic_agent(
            agent_config,
            "test_action",
            data,
            "",
            skip_guard_eval=True,
        )

        call_args = mock_builder.call_args
        assert call_args[0][2] == data


# ---------------------------------------------------------------------------
# 3. TaskPreparer._normalize_input — no fallback
# ---------------------------------------------------------------------------


class TestTaskPreparerNormalizeNamespaced:
    """TaskPreparer._normalize_input extracts content without fallback."""

    def test_subsequent_stage_missing_content_raises(self):
        """Subsequent stage raises KeyError if 'content' key is missing."""
        from agent_actions.processing.prepared_task import PreparationContext

        preparer = TaskPreparer()
        ctx = PreparationContext(
            agent_config={"agent_type": "test", "prompt": "test"},
            agent_name="test_action",
            is_first_stage=False,
        )

        # Dict without "content" key — should raise, not silently use the whole dict
        item = {"field": "value", "source_guid": "sg-1"}
        with pytest.raises(KeyError, match="content"):
            preparer._normalize_input(item, ctx)
