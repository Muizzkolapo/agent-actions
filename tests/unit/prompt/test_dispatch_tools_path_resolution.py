"""Tests for dispatch_task() tools_path auto-resolution in PromptPreparationService.

Verifies that dispatch_task() calls in prompts are resolved even when the caller
does not explicitly pass tools_path, as long as agent_config contains a resolvable
tool path (via tool_path, tools.path, or OpenAI format).
"""

from unittest.mock import patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.errors import AgentActionsError
from agent_actions.prompt.service import PromptPreparationService


def _make_agent_config(*, tool_path=None, tools=None, extra=None):
    """Build a minimal agent_config dict for prompt preparation tests."""
    config = {
        "agent_type": "test_action",
        "prompt": "inline",
        "context_scope": {"observe": ["source.*"]},
    }
    if tool_path is not None:
        config["tool_path"] = tool_path
    if tools is not None:
        config["tools"] = tools
    if extra:
        config.update(extra)
    return config


def _stub_raw_prompt(text):
    """Patch PromptFormatter.get_raw_prompt to return static text."""
    return patch(
        "agent_actions.prompt.service.PromptFormatter.get_raw_prompt",
        return_value=text,
    )


def _stub_udf(return_value="computed_result"):
    """Patch StringProcessor.call_user_function to return a static value."""
    return patch(
        "agent_actions.prompt.prompt_utils.StringProcessor.call_user_function",
        return_value=return_value,
    )


def _stub_udf_error(error_msg="Could not find function"):
    """Patch StringProcessor.call_user_function to raise an error."""
    return patch(
        "agent_actions.prompt.prompt_utils.StringProcessor.call_user_function",
        side_effect=AgentActionsError(error_msg),
    )


class TestDispatchToolsPathResolution:
    """dispatch_task() resolves when tools_path is auto-resolved from agent_config."""

    def test_dispatch_resolved_with_explicit_tools_path(self):
        """dispatch_task() works when tools_path is explicitly provided."""
        config = _make_agent_config()
        field_context = {"source": {"text": "hello"}}

        with _stub_raw_prompt("Use: dispatch_task('my_func')"), _stub_udf("dynamic_value"):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
                tools_path="/explicit/tools",
            )

        assert "dispatch_task" not in result.formatted_prompt
        assert "dynamic_value" in result.formatted_prompt

    def test_dispatch_resolved_via_tool_path_list(self):
        """dispatch_task() resolves when tools_path comes from tool_path list in config."""
        config = _make_agent_config(tool_path=["tools/my_workflow"])
        field_context = {"source": {"text": "hello"}}

        with _stub_raw_prompt("Use: dispatch_task('my_func')"), _stub_udf("resolved_output"):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
                # tools_path intentionally NOT provided
            )

        assert "dispatch_task" not in result.formatted_prompt
        assert "resolved_output" in result.formatted_prompt

    def test_dispatch_resolved_via_tool_path_string(self):
        """dispatch_task() resolves when tool_path is a plain string."""
        config = _make_agent_config(tool_path="tools/my_workflow")
        field_context = {"source": {"text": "hello"}}

        with _stub_raw_prompt("Use: dispatch_task('my_func')"), _stub_udf("string_path_result"):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

        assert "dispatch_task" not in result.formatted_prompt
        assert "string_path_result" in result.formatted_prompt

    def test_dispatch_resolved_via_tools_dict_path(self):
        """dispatch_task() resolves when tools is a dict with path key."""
        config = _make_agent_config(tools={"path": "tools/my_workflow"})
        field_context = {"source": {"text": "hello"}}

        with _stub_raw_prompt("Use: dispatch_task('my_func')"), _stub_udf("dict_path_result"):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

        assert "dispatch_task" not in result.formatted_prompt
        assert "dict_path_result" in result.formatted_prompt

    def test_no_dispatch_without_tools_config(self):
        """When no tools config exists and no dispatch calls, prompt is unchanged."""
        config = _make_agent_config()
        field_context = {"source": {"text": "hello"}}

        with _stub_raw_prompt("Plain prompt without dispatch calls"):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

        assert result.formatted_prompt == "Plain prompt without dispatch calls"

    def test_dispatch_literal_without_tools_config(self):
        """dispatch_task() passes through as literal when no tools config exists."""
        config = _make_agent_config()
        field_context = {"source": {"text": "hello"}}

        with _stub_raw_prompt("Use: dispatch_task('my_func')"):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

        # No tools config -> resolve_tools_path returns None -> dispatch skipped
        assert "dispatch_task('my_func')" in result.formatted_prompt

    def test_dispatch_error_surfaces(self):
        """dispatch_task() with missing function raises, not silently passes through."""
        config = _make_agent_config(tool_path=["tools"])
        field_context = {"source": {"text": "hello"}}

        with (
            _stub_raw_prompt("Use: dispatch_task('nonexistent')"),
            _stub_udf_error("Could not find function 'nonexistent'"),
            pytest.raises(AgentActionsError, match="Could not find function"),
        ):
            PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

    def test_multiple_dispatch_calls_all_resolved(self):
        """Multiple dispatch_task() calls in one prompt are all resolved."""
        config = _make_agent_config(tool_path=["tools"])
        field_context = {"source": {"text": "hello"}}
        call_count = 0

        def mock_call(name, path, ctx):
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"

        with (
            _stub_raw_prompt("A: dispatch_task('a') B: dispatch_task('b')"),
            patch(
                "agent_actions.prompt.prompt_utils.StringProcessor.call_user_function",
                side_effect=mock_call,
            ),
        ):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

        assert "dispatch_task" not in result.formatted_prompt
        assert "result_" in result.formatted_prompt


class TestDispatchInternalPathResolution:
    """dispatch_task() resolves via _prepare_prompt_internal when tools_path not in request."""

    def test_internal_resolves_from_agent_config(self):
        """_prepare_prompt_internal auto-resolves tools_path from agent_config."""
        config = _make_agent_config(tool_path=["tools/my_workflow"])

        with (
            _stub_raw_prompt("Content: dispatch_task('gen')"),
            _stub_udf("generated_content"),
            patch(
                "agent_actions.prompt.service.build_field_context_with_history",
                return_value={"source": {"text": "data"}},
            ),
        ):
            result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=config,
                agent_name="test",
                contents={"text": "data"},
                mode=RunMode.ONLINE,
                # tools_path intentionally NOT provided
            )

        assert "dispatch_task" not in result.formatted_prompt
        assert "generated_content" in result.formatted_prompt

    def test_explicit_tools_path_takes_precedence(self):
        """Explicit tools_path overrides auto-resolution from agent_config."""
        config = _make_agent_config(tool_path=["config/path"])

        calls = []

        def capture_call(name, path, ctx):
            calls.append(path)
            return "result"

        with (
            _stub_raw_prompt("dispatch_task('func')"),
            patch(
                "agent_actions.prompt.prompt_utils.StringProcessor.call_user_function",
                side_effect=capture_call,
            ),
            patch(
                "agent_actions.prompt.service.build_field_context_with_history",
                return_value={"source": {"text": "data"}},
            ),
        ):
            PromptPreparationService.prepare_prompt_with_context(
                agent_config=config,
                agent_name="test",
                contents={"text": "data"},
                tools_path="/explicit/override",
            )

        assert calls[0] == "/explicit/override"
