"""End-to-end simulation of dispatch_task() resolution.

Creates a real UDF on disk, configures agent_config to point at it,
and verifies the full pipeline: prompt rendering → tools_path resolution
→ UDF loading → dispatch_task replacement. No mocks on the dispatch path.
"""

import sys
from unittest.mock import patch

import pytest

from agent_actions.prompt.service import PromptPreparationService
from agent_actions.utils.module_loader import clear_module_cache


@pytest.fixture()
def tools_dir(tmp_path):
    """Create a tools directory with a real UDF module."""
    tools = tmp_path / "tools"
    tools.mkdir()

    # A simple UDF that returns a computed string
    (tools / "get_opener.py").write_text(
        "def get_opener(context_data, *args):\n"
        '    return "During monitoring, you notice an anomaly"\n'
    )

    # A UDF that uses context data
    (tools / "summarize.py").write_text(
        "import json\n"
        "def summarize(context_data, *args):\n"
        "    data = json.loads(context_data) if isinstance(context_data, str) else context_data\n"
        "    keys = list(data.keys()) if isinstance(data, dict) else []\n"
        '    return f"Summary of {len(keys)} fields"\n'
    )

    # A UDF that returns None (should error)
    (tools / "bad_udf.py").write_text("def bad_udf(context_data, *args):\n    return None\n")

    yield tools

    # Clean up loaded modules from sys.modules
    clear_module_cache()
    for name in list(sys.modules):
        if name in ("get_opener", "summarize", "bad_udf", "sub_opener"):
            del sys.modules[name]


def _stub_raw_prompt(text):
    return patch(
        "agent_actions.prompt.service.PromptFormatter.get_raw_prompt",
        return_value=text,
    )


class TestDispatchTaskEndToEnd:
    """Full pipeline: real UDF on disk, no mocks on the dispatch path."""

    def test_dispatch_passes_context_to_udf(self, tools_dir):
        """The UDF receives the LLM context (with observed fields) as its first argument."""
        config = {
            "agent_type": "test",
            "prompt": "inline",
            "context_scope": {"observe": ["source.*"]},
            "tool_path": [str(tools_dir)],
        }
        field_context = {"source": {"text": "hello", "category": "test"}}

        with _stub_raw_prompt("Result: dispatch_task('summarize')"):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

        assert "dispatch_task" not in result.formatted_prompt
        # source.* observe produces {"source": {...}} in llm_context — 1 top-level key.
        # "0 fields" would mean empty context wasn't passed; "1 fields" proves it was.
        assert "Summary of 1 fields" in result.formatted_prompt

    def test_dispatch_none_return_raises(self, tools_dir):
        """UDF returning None raises AgentActionsError, not silent passthrough."""
        from agent_actions.errors import AgentActionsError

        config = {
            "agent_type": "test",
            "prompt": "inline",
            "context_scope": {"observe": ["source.*"]},
            "tool_path": [str(tools_dir)],
        }
        field_context = {"source": {"text": "hello"}}

        with (
            _stub_raw_prompt("Value: dispatch_task('bad_udf')"),
            pytest.raises(AgentActionsError, match="returned None"),
        ):
            PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

    def test_dispatch_missing_function_raises(self, tools_dir):
        """Referencing a non-existent UDF raises, not literal passthrough."""
        from agent_actions.errors import ConfigurationError

        config = {
            "agent_type": "test",
            "prompt": "inline",
            "context_scope": {"observe": ["source.*"]},
            "tool_path": [str(tools_dir)],
        }
        field_context = {"source": {"text": "hello"}}

        with (
            _stub_raw_prompt("Value: dispatch_task('nonexistent_func')"),
            pytest.raises(ConfigurationError, match="nonexistent_func"),
        ):
            PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

    def test_dispatch_auto_resolves_without_explicit_tools_path(self, tools_dir):
        """The fix: tools_path auto-resolved from config, not passed by caller."""
        config = {
            "agent_type": "test",
            "prompt": "inline",
            "context_scope": {"observe": ["source.*"]},
            "tool_path": [str(tools_dir)],
        }
        field_context = {"source": {"text": "hello"}}

        # Call prepare_prompt_with_field_context WITHOUT tools_path arg.
        # Before the fix, this would pass "dispatch_task('get_opener')" as literal.
        with _stub_raw_prompt("Opener: dispatch_task('get_opener')"):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
                # tools_path intentionally omitted — auto-resolution under test
            )

        assert "dispatch_task" not in result.formatted_prompt
        assert "During monitoring, you notice an anomaly" in result.formatted_prompt

    def test_dispatch_resolves_function_in_subdirectory(self, tools_dir):
        """dispatch_task() finds a UDF located in a subdirectory of tools_path."""
        # Create a function inside a subdirectory
        subdir = tools_dir / "qanalabs-quiz-gen"
        subdir.mkdir()
        (subdir / "sub_opener.py").write_text(
            'def sub_opener(context_data, *args):\n    return "Found in subdirectory"\n'
        )

        config = {
            "agent_type": "test",
            "prompt": "inline",
            "context_scope": {"observe": ["source.*"]},
            "tool_path": [str(tools_dir)],
        }
        field_context = {"source": {"text": "hello"}}

        with _stub_raw_prompt("Result: dispatch_task('sub_opener')"):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

        assert "dispatch_task" not in result.formatted_prompt
        assert "Found in subdirectory" in result.formatted_prompt

    def test_no_tools_config_leaves_literal(self):
        """Without any tools config, dispatch_task passes through as literal text."""
        config = {
            "agent_type": "test",
            "prompt": "inline",
            "context_scope": {"observe": ["source.*"]},
        }
        field_context = {"source": {"text": "hello"}}

        with _stub_raw_prompt("Value: dispatch_task('anything')"):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

        assert "dispatch_task('anything')" in result.formatted_prompt
