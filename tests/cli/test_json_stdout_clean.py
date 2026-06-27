"""Regression tests for --json stdout cleanliness."""

from __future__ import annotations

import inspect
import sys

import pytest
from rich.console import Console

from agent_actions.utils.udf_management.registry import clear_registry
from agent_actions.workflow.config_pipeline import _discover_udfs_from_path
from agent_actions.workflow.coordinator import AgentWorkflow


def _evict_udf_modules() -> None:
    """Drop framework-imported UDF modules so the next discovery actually re-imports.

    discover_udfs() skips files whose synthetic module name is already in
    sys.modules — otherwise repeated calls with different tmp_paths would
    silently no-op and the @udf_tool decorator never re-fires.
    """
    for name in [k for k in sys.modules if k.startswith("agent_actions._udfs.")]:
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _isolated_registry():
    clear_registry()
    _evict_udf_modules()
    yield
    clear_registry()
    _evict_udf_modules()


class TestCoordinatorConsoleTargetsStderr:
    def test_agent_workflow_init_constructs_stderr_console(self):
        src = inspect.getsource(AgentWorkflow.__init__)
        assert "Console(stderr=True)" in src, (
            "Bare Console() writes to stdout and breaks `agac <cmd> --json | jq .`."
        )


class TestDiscoveryProgressChannel:
    @staticmethod
    def _write_noop_udf(tools_dir):
        tools_dir.mkdir()
        (tools_dir / "noop.py").write_text(
            "from agent_actions.utils.udf_management.registry import udf_tool\n"
            "\n"
            "@udf_tool\n"
            "def noop(x):\n"
            "    return x\n"
        )

    def test_stderr_console_keeps_discovery_off_stdout(self, tmp_path, capfd):
        tools = tmp_path / "tools"
        self._write_noop_udf(tools)

        console = Console(file=sys.stderr, force_terminal=False, width=120)
        _discover_udfs_from_path(str(tools), project_root=None, console=console)

        captured = capfd.readouterr()
        assert "Discovering Tools" not in captured.out, f"leaked to stdout: {captured.out!r}"
        assert "Discovering Tools" in captured.err, f"missing from stderr: {captured.err!r}"

    def test_stdout_console_demonstrates_the_bug(self, tmp_path, capfd):
        tools = tmp_path / "tools"
        self._write_noop_udf(tools)

        console = Console(file=sys.stdout, force_terminal=False, width=120)
        _discover_udfs_from_path(str(tools), project_root=None, console=console)

        captured = capfd.readouterr()
        assert "Discovering Tools" in captured.out, (
            "stdout-bound Console no longer leaks — print site moved"
        )
