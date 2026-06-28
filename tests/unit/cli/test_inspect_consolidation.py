"""Tests for VIOL-0008: unified `agac inspect` command.

Covers the four flag modes (--yaml, --validate, --dry-run, --json) plus
mutual-exclusion and the absent-flag default. Uses MagicMock to fake the
WorkflowInspector so we don't need a fixture workflow on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from agent_actions.cli.inspect import inspect
from agent_actions.errors.preflight import PreFlightValidationError


def _invoke(*args: str):
    """Invoke `agac inspect ...` and return the click Result.

    Patches ensure_in_project so tests don't need a real project tree.
    Uses ``mix_stderr=False`` so JSON-mode tests can parse stdout
    without the project-root banner (which goes to stderr).
    """
    try:
        runner = CliRunner(mix_stderr=False)
    except TypeError:
        # Click ≥ 8.2 dropped the mix_stderr kwarg (streams are always
        # split). Fall back to the default constructor.
        runner = CliRunner()
    with patch(
        "agent_actions.cli.inspect.ensure_in_project",
        return_value=Path("/fake/project"),
    ):
        return runner.invoke(inspect, list(args))


def _stdout(result) -> str:
    """Return result stdout regardless of CliRunner version (mixed or split)."""
    # Click ≥ 8.2: result.stdout is always stdout-only.
    # Click < 8.2 with mix_stderr=False: same.
    # Click < 8.2 with default mix: result.output mixes stderr.
    try:
        return result.stdout
    except (AttributeError, ValueError):
        return result.output


# ── --yaml replaces agac compile ─────────────────────────────────────────


class TestInspectYaml:
    def test_outputs_rendered_yaml(self):
        with patch("agent_actions.cli.inspect.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.render.return_value = "name: test\nactions: []\n"
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test_workflow", "--yaml")

        assert result.exit_code == 0, result.output
        assert "name: test" in result.output
        mock_inspector.render.assert_called_once()

    def test_skips_validation(self):
        """--yaml must NOT trigger validation — that's the compile contract."""
        with patch("agent_actions.cli.inspect.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.render.return_value = "ok: true\n"
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test", "--yaml")

        assert result.exit_code == 0, result.output
        mock_inspector.validate.assert_not_called()
        mock_inspector.load.assert_not_called()


# ── --validate produces a pass/fail report ───────────────────────────────


class TestInspectValidate:
    def test_validate_pass(self):
        with patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.action_configs = {"a": {}}
            mock_inspector.execution_order = ["a"]
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test", "--validate")

        assert result.exit_code == 0, result.output
        assert "passed" in result.output.lower() or "ok" in result.output.lower()

    def test_validate_fail_exits_nonzero(self):
        """Failed validation should exit non-zero (CI signal)."""
        with patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.validate.side_effect = PreFlightValidationError(
                "schema broken", hint="fix it"
            )
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test", "--validate")

        assert result.exit_code != 0, result.output

    def test_validate_json_pass(self):
        with patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.action_configs = {"a": {}}
            mock_inspector.execution_order = ["a"]
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test", "--validate", "--json")

        assert result.exit_code == 0, result.output
        # First line should be parseable JSON (banner goes to stderr)
        payload = json.loads(_stdout(result).strip())
        assert payload["status"] == "ok"
        assert payload["workflow"] == "test"

    def test_validate_json_fail(self):
        with patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.validate.side_effect = PreFlightValidationError(
                "schema broken", hint="fix it"
            )
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test", "--validate", "--json")

        assert result.exit_code != 0, result.output
        # The JSON payload should be parseable even on failure
        # (banner is stderr, JSON is stdout)
        if result.output.strip():
            payload = json.loads(_stdout(result).strip())
            assert payload["status"] == "failed"
            assert payload["workflow"] == "test"


# ── --dry-run shows graph + validation + estimate ────────────────────────


class TestInspectDryRun:
    def test_dry_run_pass(self):
        with patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.action_configs = {"a": {}, "b": {}}
            mock_inspector.execution_order = ["a", "b"]
            mock_inspector.get_levels.return_value = [["a"], ["b"]]
            mock_inspector.get_context_scope.return_value = {
                "a": {"scope": "observe"},
                "b": {"scope": "observe"},
            }
            mock_inspector.estimate.return_value = {
                "action_count": 2,
                "llm_calls": 2,
                "guarded_actions": 0,
            }
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test", "--dry-run")

        assert result.exit_code == 0, result.output
        assert "Level 1" in result.output
        assert "Level 2" in result.output

    def test_dry_run_json(self):
        with patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.action_configs = {"a": {}}
            mock_inspector.execution_order = ["a"]
            mock_inspector.get_levels.return_value = [["a"]]
            mock_inspector.get_context_scope.return_value = {"a": {"scope": "observe"}}
            mock_inspector.estimate.return_value = {
                "action_count": 1,
                "llm_calls": 0,
                "guarded_actions": 0,
            }
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test", "--dry-run", "--json")

        assert result.exit_code == 0, result.output
        payload = json.loads(_stdout(result).strip())
        assert payload["status"] == "ok"
        assert payload["execution_levels"] == [["a"]]
        assert payload["estimate"]["action_count"] == 1


# ── Default behavior (no flags) ──────────────────────────────────────────


class TestInspectDefault:
    def test_default_shows_graph(self):
        with patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.action_configs = {"fetch": {}, "analyze": {}}
            mock_inspector.execution_order = ["fetch", "analyze"]
            mock_inspector.get_levels.return_value = [["fetch"], ["analyze"]]
            mock_inspector.get_context_scope.return_value = {
                "fetch": {"scope": "observe"},
                "analyze": {"scope": "observe"},
            }
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test")

        assert result.exit_code == 0, result.output
        assert "fetch" in result.output
        assert "analyze" in result.output

    def test_default_json(self):
        with patch("agent_actions.cli.inspect_base.WorkflowInspector") as mock_inspector_cls:
            mock_inspector = MagicMock()
            mock_inspector.action_configs = {"a": {}}
            mock_inspector.execution_order = ["a"]
            mock_inspector.get_levels.return_value = [["a"]]
            mock_inspector.get_context_scope.return_value = {"a": {"scope": "observe"}}
            mock_inspector_cls.return_value = mock_inspector

            result = _invoke("-a", "test", "--json")

        assert result.exit_code == 0, result.output
        payload = json.loads(_stdout(result).strip())
        assert payload["validation_ok"] is True
        assert payload["execution_levels"] == [["a"]]


# ── Flag mutual exclusion ───────────────────────────────────────────────


class TestInspectFlagExclusion:
    @pytest.mark.parametrize(
        "flags",
        [
            ("--yaml", "--validate"),
            ("--yaml", "--dry-run"),
            ("--validate", "--dry-run"),
            ("--yaml", "--validate", "--dry-run"),
        ],
    )
    def test_combinations_rejected(self, flags):
        result = _invoke("-a", "test", *flags)
        assert result.exit_code != 0, result.output
        assert "only one" in result.output.lower() or "mutually" in result.output.lower()


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


# ── compile/render removal regression ────────────────────────────────────


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
