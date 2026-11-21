"""A config stage error carries the workflow name and the stage, and keeps any inner context."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigurationError, UDFLoadError
from agent_actions.workflow.config_pipeline import (
    _discover_udfs_from_path,
    _run_config_stage,
    load_workflow_configs,
)
from agent_actions.workflow.models import WorkflowPaths, WorkflowRuntimeConfig


class TestRunConfigStage:
    """Verify _run_config_stage enriches exceptions correctly."""

    def test_success_returns_value(self):
        """Happy path: function return value is passed through."""
        result = _run_config_stage(lambda: 42, "load_configs", "test_agent")
        assert result == 42

    def test_enriches_with_pipeline_stage_not_operation(self):
        """Must use 'pipeline_stage' key so inner 'operation' is preserved."""
        inner = ConfigurationError(
            "template error",
            context={"operation": "template_rendering", "config_path": "/a/b.yml"},
        )

        def fail():
            raise inner

        with pytest.raises(ConfigurationError) as exc_info:
            _run_config_stage(fail, "load_configs", "test_agent")

        ctx = exc_info.value.context
        # Inner 'operation' must NOT be overwritten
        assert ctx["operation"] == "template_rendering"
        # Pipeline stage stored under a separate key
        assert ctx["pipeline_stage"] == "load_configs"
        assert ctx["agent"] == "test_agent"

    def test_exception_without_context_attr(self):
        """Bare Exception (no .context) gets a fresh dict."""

        def fail():
            raise ValueError("oops")

        with pytest.raises(ValueError) as exc_info:
            _run_config_stage(fail, "validate_agent_name", "my_agent")

        ctx = exc_info.value.context
        assert isinstance(ctx, dict)
        assert ctx["pipeline_stage"] == "validate_agent_name"
        assert ctx["agent"] == "my_agent"

    def test_exception_with_existing_context_dict(self):
        """Exception that already has a dict .context gets enriched additively."""
        err = RuntimeError("fail")
        err.context = {"existing_key": "preserved"}

        def fail():
            raise err

        with pytest.raises(RuntimeError) as exc_info:
            _run_config_stage(fail, "merge_agent_configs", "test_agent")

        ctx = exc_info.value.context
        assert ctx["existing_key"] == "preserved"
        assert ctx["pipeline_stage"] == "merge_agent_configs"

    def test_exception_with_non_dict_context_replaced(self):
        """If .context is a non-dict (e.g. string), it gets replaced with a fresh dict."""
        err = RuntimeError("fail")
        err.context = "not a dict"

        def fail():
            raise err

        with pytest.raises(RuntimeError) as exc_info:
            _run_config_stage(fail, "determine_execution_order", "test_agent")

        ctx = exc_info.value.context
        assert isinstance(ctx, dict)
        assert ctx["pipeline_stage"] == "determine_execution_order"

    def test_passes_args_to_function(self):
        """Extra args are forwarded to the wrapped function."""
        values = []

        def fn(a, b):
            values.append((a, b))

        _run_config_stage(fn, "test_stage", "test_agent", "x", "y")
        assert values == [("x", "y")]

    def test_a_failure_before_the_config_parses_names_the_workflow(self):
        """The workflow name comes from the config path, which is known before the file parses."""
        manager = MagicMock()
        manager.agent_name = None
        manager.load_configs.side_effect = ConfigurationError("render failed")
        config = WorkflowRuntimeConfig(
            paths=WorkflowPaths(
                constructor_path="/p/agent_workflow/quiz/agent_config/quiz.yml",
                user_code_path=None,
                default_path="/p/agent_actions.yml",
            ),
            use_tools=False,
            manager=manager,
        )

        with pytest.raises(ConfigurationError) as exc_info:
            load_workflow_configs(config, MagicMock(), fire_events=False)

        assert exc_info.value.context["agent"] == "quiz"
        assert exc_info.value.context["pipeline_stage"] == "load_configs"

    def test_the_initialization_event_names_the_workflow_before_the_config_parses(self):
        manager = MagicMock()
        manager.agent_name = None
        manager.load_configs.side_effect = ConfigurationError("render failed")
        config = WorkflowRuntimeConfig(
            paths=WorkflowPaths(
                constructor_path="/p/agent_workflow/quiz/agent_config/quiz.yml",
                user_code_path=None,
                default_path="/p/agent_actions.yml",
            ),
            use_tools=False,
            manager=manager,
        )

        with patch("agent_actions.workflow.config_pipeline.fire_event") as fired:
            with pytest.raises(ConfigurationError):
                load_workflow_configs(config, MagicMock(), fire_events=True)

        (event,) = [call.args[0] for call in fired.call_args_list]
        assert type(event).__name__ == "WorkflowInitializationStartEvent"
        assert event.workflow_name == "quiz"


class TestDiscoverUDFsFromPathTypedHandling:
    """_discover_udfs_from_path must wrap discover_udfs in a typed try/except
    so UDFLoadError carries the configured path context — not just the
    per-file path UDFLoadError already records — when bubbled up."""

    def test_udf_load_error_is_enriched_with_search_path(self, tmp_path):
        path_dir = tmp_path / "tools"
        path_dir.mkdir()
        console = MagicMock()
        raised = UDFLoadError(module="proj.bad", file="bad.py", error="boom")

        with patch("agent_actions.workflow.config_pipeline.discover_udfs", side_effect=raised):
            with pytest.raises(UDFLoadError) as exc_info:
                _discover_udfs_from_path(str(path_dir), None, console)

        # Original identity preserved.
        assert exc_info.value.context["module"] == "proj.bad"
        # Pipeline context added so the formatter / logs can name the
        # workflow-level search location.
        assert exc_info.value.context["pipeline_stage"] == "discover_udfs"
        assert exc_info.value.context["search_path"] == str(path_dir.resolve())
        assert exc_info.value.context["requested_path"] == str(path_dir)

    def test_discovery_sentinel_error_propagates_with_enrichment(self, tmp_path):
        path_dir = tmp_path / "tools"
        path_dir.mkdir()
        console = MagicMock()
        raised = UDFLoadError(
            module=UDFLoadError.DISCOVERY_SENTINEL,
            file=str(path_dir),
            error="User code directory not found",
        )

        with patch("agent_actions.workflow.config_pipeline.discover_udfs", side_effect=raised):
            with pytest.raises(UDFLoadError) as exc_info:
                _discover_udfs_from_path(str(path_dir), None, console)

        assert exc_info.value.context["module"] == UDFLoadError.DISCOVERY_SENTINEL
        assert exc_info.value.context["search_path"] == str(path_dir.resolve())
