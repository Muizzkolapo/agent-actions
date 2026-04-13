"""Tests for _run_config_stage in config_pipeline.py.

Covers:
- pipeline_stage key (not operation) to avoid overwriting inner context
- isinstance guard when .context is not a dict
- agent name propagation
- Exception without .context attribute
- Exception with existing .context dict
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.workflow.config_pipeline import _run_config_stage


def _make_manager(agent_name: str = "test_agent") -> MagicMock:
    """Return a mock ConfigManager with the given agent_name."""
    manager = MagicMock()
    manager.agent_name = agent_name
    return manager


class TestRunConfigStage:
    """Verify _run_config_stage enriches exceptions correctly."""

    def test_success_returns_value(self):
        """Happy path: function return value is passed through."""
        manager = _make_manager()
        result = _run_config_stage(lambda: 42, "load_configs", manager)
        assert result == 42

    def test_enriches_with_pipeline_stage_not_operation(self):
        """Must use 'pipeline_stage' key so inner 'operation' is preserved."""
        manager = _make_manager()
        inner = ConfigurationError(
            "template error",
            context={"operation": "template_rendering", "config_path": "/a/b.yml"},
        )

        def fail():
            raise inner

        with pytest.raises(ConfigurationError) as exc_info:
            _run_config_stage(fail, "load_configs", manager)

        ctx = exc_info.value.context
        # Inner 'operation' must NOT be overwritten
        assert ctx["operation"] == "template_rendering"
        # Pipeline stage stored under a separate key
        assert ctx["pipeline_stage"] == "load_configs"
        assert ctx["agent"] == "test_agent"

    def test_exception_without_context_attr(self):
        """Bare Exception (no .context) gets a fresh dict."""
        manager = _make_manager("my_agent")

        def fail():
            raise ValueError("oops")

        with pytest.raises(ValueError) as exc_info:
            _run_config_stage(fail, "validate_agent_name", manager)

        ctx = exc_info.value.context
        assert isinstance(ctx, dict)
        assert ctx["pipeline_stage"] == "validate_agent_name"
        assert ctx["agent"] == "my_agent"

    def test_exception_with_existing_context_dict(self):
        """Exception that already has a dict .context gets enriched additively."""
        manager = _make_manager()
        err = RuntimeError("fail")
        err.context = {"existing_key": "preserved"}

        def fail():
            raise err

        with pytest.raises(RuntimeError) as exc_info:
            _run_config_stage(fail, "merge_agent_configs", manager)

        ctx = exc_info.value.context
        assert ctx["existing_key"] == "preserved"
        assert ctx["pipeline_stage"] == "merge_agent_configs"

    def test_exception_with_non_dict_context_replaced(self):
        """If .context is a non-dict (e.g. string), it gets replaced with a fresh dict."""
        manager = _make_manager()
        err = RuntimeError("fail")
        err.context = "not a dict"

        def fail():
            raise err

        with pytest.raises(RuntimeError) as exc_info:
            _run_config_stage(fail, "determine_execution_order", manager)

        ctx = exc_info.value.context
        assert isinstance(ctx, dict)
        assert ctx["pipeline_stage"] == "determine_execution_order"

    def test_passes_args_to_function(self):
        """Extra args are forwarded to the wrapped function."""
        manager = _make_manager()
        values = []

        def fn(a, b):
            values.append((a, b))

        _run_config_stage(fn, "test_stage", manager, "x", "y")
        assert values == [("x", "y")]

    def test_manager_without_agent_name_falls_back(self):
        """When manager has no agent_name attr, uses 'unknown'."""
        manager = MagicMock(spec=[])  # No attributes at all

        def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError) as exc_info:
            _run_config_stage(fail, "load_configs", manager)

        assert exc_info.value.context["agent"] == "unknown"
