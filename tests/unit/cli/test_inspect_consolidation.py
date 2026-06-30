"""Tests for `agac inspect`.

Covers the default form and the two subcommands. Uses MagicMock to
fake the WorkflowInspector so we don't need a fixture workflow on disk.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from agent_actions.cli.inspect import inspect


def _invoke(*args: str):
    """Invoke `agac inspect ...` and return the click Result.

    Patches ensure_in_project so tests don't need a real project tree.
    """
    runner = CliRunner()
    with patch(
        "agent_actions.cli.inspect.ensure_in_project",
        return_value=Path("/fake/project"),
    ):
        return runner.invoke(inspect, list(args))


# ── Default behavior ────────────────────────────────────────────────────


class TestInspectDefault:
    def test_default_shows_graph(self):
        with patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.action_configs = {"fetch": {}, "analyze": {}}
            mock_inspector.execution_order = ["fetch", "analyze"]
            mock_inspector.get_levels.return_value = [["fetch"], ["analyze"]]
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test")

        assert result.exit_code == 0, result.output
        assert "fetch" in result.output
        assert "analyze" in result.output

    def test_user_code_forwarded_to_inspector(self):
        """`-u <path>` must reach WorkflowInspector as user_code_path."""
        with patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.action_configs = {"a": {}}
            mock_inspector.execution_order = ["a"]
            mock_inspector.get_levels.return_value = [["a"]]
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test", "-u", "my_tools")

        assert result.exit_code == 0, result.output
        kwargs = mock_inspector_cls.call_args.kwargs
        assert kwargs.get("user_code_path") == "my_tools"


# ── --agent is required when no subcommand ──────────────────────────────


class TestInspectAgentRequired:
    def test_missing_agent_errors(self):
        runner = CliRunner()
        with patch(
            "agent_actions.cli.inspect.ensure_in_project",
            return_value=Path("/fake/project"),
        ):
            result = runner.invoke(inspect, [])
        assert result.exit_code != 0
        assert "agent" in result.output.lower()


class TestWorkflowInspectorGetLevels:
    """get_levels() must include non-operational agents that
    ConfigManager omits from execution_order.
    """

    def test_get_levels_includes_non_operational_actions(self):
        from agent_actions.services.workflow_inspector import WorkflowInspector

        inspector = WorkflowInspector.__new__(WorkflowInspector)
        inspector.agent_name = "wf"
        inspector.project_root = None
        inspector.user_code_path = None
        inspector.paths = MagicMock()
        inspector._config_path = Path("/fake/wf.yml")
        # Two operational, one non-operational (absent from execution_order).
        inspector.action_configs = {
            "op_a": {"depends_on": []},
            "op_b": {"depends_on": ["op_a"]},
            "non_op_c": {"depends_on": ["op_b"]},
        }
        inspector.execution_order = ["op_a", "op_b"]
        inspector._loaded = True

        levels = inspector.get_levels()
        flat = [name for level in levels for name in level]
        assert "non_op_c" in flat, "non-operational action was dropped"
        # And it should be placed AFTER its dep, not in a 'cycle' bucket.
        op_b_level = next(i for i, lvl in enumerate(levels) if "op_b" in lvl)
        non_op_c_level = next(i for i, lvl in enumerate(levels) if "non_op_c" in lvl)
        assert non_op_c_level > op_b_level


class TestVersionGroupCollapse:
    """Version-expanded actions (`is_versioned_agent=True` with a
    `version_base_name`) collapse to ``<base> (×N)`` in the parallel
    fan-out display. Plain ``_N`` suffix names without the runtime
    flag are kept distinct — regex-only collapse would fold unrelated
    sibling actions named `step_1` / `step_2` into one pill.
    """

    def _versioned(self, base, n):
        return [
            (
                f"{base}_{i}",
                {"is_versioned_agent": True, "version_base_name": base},
            )
            for i in range(1, n + 1)
        ]

    def _collapse(self, name_cfg_pairs):
        from agent_actions.cli.inspect import InspectCommand

        cmd = InspectCommand.__new__(InspectCommand)
        cmd._inspector_action_configs = dict(name_cfg_pairs)
        return cmd._collapse_version_groups([name for name, _ in name_cfg_pairs])

    def test_versioned_group_collapses(self):
        assert self._collapse(self._versioned("foo", 3)) == ["foo (×3)"]

    def test_singleton_versioned_keeps_full_name(self):
        # Only one variant — no `(×1)` noise.
        assert self._collapse(self._versioned("foo", 1)) == ["foo_1"]

    def test_non_versioned_pass_through_even_with_n_suffix(self):
        # `step_1` / `step_2` look version-shaped but the runtime never
        # flagged them as versioned — keep them distinct.
        pairs = [("step_1", {}), ("step_2", {})]
        assert self._collapse(pairs) == ["step_1", "step_2"]

    def test_mixed_versioned_and_singleton(self):
        pairs = [
            *self._versioned("validate_final_question", 3),
            *self._versioned("verify_answer", 3),
            ("contract_scenario", {}),
        ]
        assert self._collapse(pairs) == [
            "validate_final_question (×3)",
            "verify_answer (×3)",
            "contract_scenario",
        ]

    def test_out_of_order_versions(self):
        pairs = [
            ("foo_3", {"is_versioned_agent": True, "version_base_name": "foo"}),
            ("foo_1", {"is_versioned_agent": True, "version_base_name": "foo"}),
            ("foo_2", {"is_versioned_agent": True, "version_base_name": "foo"}),
        ]
        assert self._collapse(pairs) == ["foo (×3)"]


class TestCompileRemoved:
    def test_no_compile_module(self):
        """`agent_actions.cli.compile` is gone — guard against re-introduction."""
        with pytest.raises(ImportError):
            __import__("agent_actions.cli.compile")

    def test_no_compile_subcommand_registered(self):
        """main.py no longer imports or registers compile/render.

        Reads main.py source text instead of instantiating CLI(), which
        would fire CLI init events and register signal handlers — too
        much side effect for a simple registration check.
        """
        from agent_actions.cli import main as main_module

        source = Path(main_module.__file__).read_text()
        assert "cli.compile" not in source, "compile import re-introduced"
        assert "add_command(compile)" not in source, "compile command re-registered"
        assert "add_command(render)" not in source, "render command re-registered"


# ── Group flag propagation to subcommands ───────────────────────────────


class TestGroupFlagPropagation:
    """``agac inspect -a foo action <name>`` — Click eats ``-a`` at the
    group level; subcommands must inherit it via ``ctx.default_map``.
    """

    def test_agent_passed_before_subcommand_reaches_subcommand(self):
        """Regression: ``-a foo action <name>`` used to fail with
        'Missing option -a'. The group must propagate the agent.
        """
        with (
            patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls,
            patch(
                "agent_actions.cli.cli_decorators.ensure_in_project",
                return_value=Path("/fake/project"),
            ),
        ):
            mock_inspector = MagicMock()
            mock_inspector.action_configs = {"a": {}}
            mock_inspector.execution_order = ["a"]
            mock_inspector.schema_service = None
            mock_inspector_cls.return_value = mock_inspector

            runner = CliRunner()
            result = runner.invoke(inspect, ["-a", "test_workflow", "action", "a"])

        assert result.exit_code == 0, result.output
        # WorkflowInspector should be constructed with the propagated agent.
        kwargs = mock_inspector_cls.call_args.kwargs
        assert kwargs.get("agent_name") == "test_workflow"

    def test_user_code_propagates_too(self):
        with (
            patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls,
            patch(
                "agent_actions.cli.cli_decorators.ensure_in_project",
                return_value=Path("/fake/project"),
            ),
        ):
            mock_inspector = MagicMock()
            mock_inspector.action_configs = {"a": {}}
            mock_inspector.execution_order = ["a"]
            mock_inspector.schema_service = None
            mock_inspector_cls.return_value = mock_inspector

            runner = CliRunner()
            result = runner.invoke(inspect, ["-a", "wf", "-u", "my_tools", "action", "a"])

        assert result.exit_code == 0, result.output
        kwargs = mock_inspector_cls.call_args.kwargs
        assert kwargs.get("user_code_path") == "my_tools"

    def test_subcommand_explicit_agent_wins_over_group(self):
        """When both group and subcommand pass -a, subcommand wins."""
        with (
            patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls,
            patch(
                "agent_actions.cli.cli_decorators.ensure_in_project",
                return_value=Path("/fake/project"),
            ),
        ):
            mock_inspector = MagicMock()
            mock_inspector.action_configs = {"a": {}}
            mock_inspector.execution_order = ["a"]
            mock_inspector.schema_service = None
            mock_inspector_cls.return_value = mock_inspector

            runner = CliRunner()
            result = runner.invoke(inspect, ["-a", "group_wf", "action", "-a", "sub_wf", "a"])

        assert result.exit_code == 0, result.output
        kwargs = mock_inspector_cls.call_args.kwargs
        assert kwargs.get("agent_name") == "sub_wf"
