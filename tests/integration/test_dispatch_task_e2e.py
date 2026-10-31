"""End-to-end simulation of dispatch_task() resolution.

Creates a real UDF on disk, configures agent_config to point at it,
and verifies the full pipeline: prompt rendering → tools_path resolution
→ UDF loading → dispatch_task replacement. No mocks on the dispatch path.
"""

import sys
from unittest.mock import patch

import pytest

from agent_actions.errors import AgentActionsError, ConfigurationError
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

    @pytest.mark.parametrize(
        ("prompt", "field_context", "expected"),
        [
            # source.* observe produces {"source": {...}} in llm_context — 1 top-level key.
            # "0 fields" would mean empty context wasn't passed; "1 fields" proves it was.
            pytest.param(
                "Result: dispatch_task('summarize')",
                {"source": {"text": "hello", "category": "test"}},
                "Summary of 1 fields",
                id="passes-context-to-udf",
            ),
            # No tools_path is passed below: it must be auto-resolved from config, or
            # "dispatch_task('get_opener')" is sent as literal text.
            pytest.param(
                "Opener: dispatch_task('get_opener')",
                {"source": {"text": "hello"}},
                "During monitoring, you notice an anomaly",
                id="auto-resolves-without-explicit-tools-path",
            ),
        ],
    )
    def test_dispatch_replaces_the_call_with_what_the_udf_returns(
        self, tools_dir, prompt, field_context, expected
    ):
        """The UDF receives the LLM context (with observed fields) as its first argument."""
        config = {
            "agent_type": "test",
            "prompt": "inline",
            "context_scope": {"observe": ["source.*"]},
            "tool_path": [str(tools_dir)],
        }

        with _stub_raw_prompt(prompt):
            result = PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

        assert "dispatch_task" not in result.formatted_prompt
        assert expected in result.formatted_prompt

    @pytest.mark.parametrize(
        ("prompt", "error", "match"),
        [
            pytest.param(
                "Value: dispatch_task('bad_udf')",
                AgentActionsError,
                "returned None",
                id="none-return-raises-not-silent-passthrough",
            ),
            pytest.param(
                "Value: dispatch_task('nonexistent_func')",
                ConfigurationError,
                "nonexistent_func",
                id="missing-function-raises-not-literal-passthrough",
            ),
        ],
    )
    def test_dispatch_raises(self, tools_dir, prompt, error, match):
        config = {
            "agent_type": "test",
            "prompt": "inline",
            "context_scope": {"observe": ["source.*"]},
            "tool_path": [str(tools_dir)],
        }
        field_context = {"source": {"text": "hello"}}

        with _stub_raw_prompt(prompt), pytest.raises(error, match=match):
            PromptPreparationService.prepare_prompt_with_field_context(
                agent_config=config,
                agent_name="test",
                contents={},
                field_context=field_context,
            )

    def test_dispatch_resolves_function_in_subdirectory(self, tools_dir):
        """dispatch_task() finds a UDF located in a subdirectory of tools_path."""
        subdir = tools_dir / "nested-tools"
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
