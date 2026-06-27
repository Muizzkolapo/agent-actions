"""Regression tests for `--json` stdout cleanliness.

Every `agac … --json` command must emit a single jq-parseable JSON document
on stdout. The framework's coordinator owns a single rich Console used by
every progress-emitting call site downstream. If that Console writes to
stdout, status banners ("Discovering Tools …", "Discovered N Tools")
appear above the JSON payload and break `jq`.

Two complementary regressions live here:

* A source-level property test that pins the Console-construction literal
  at the coordinator. Cheap and fast; fails loudly if anyone reverts to a
  stdout-bound Console.
* A behavioral test exercising the discovery print site directly. It feeds
  the print site a stderr-bound Console and asserts stdout stays clean
  while stderr receives the banner.
"""

from __future__ import annotations

import inspect as inspect_mod
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
    """The coordinator's shared rich Console must write to stderr."""

    def test_agent_workflow_init_constructs_stderr_console(self):
        """`AgentWorkflow.__init__` must construct its Console with stderr=True.

        Bare `Console()` defaults to `sys.stdout`. Stdout is reserved for
        the machine-readable payload of any `--json` command; routing
        progress text there breaks downstream JSON parsers.
        """
        src = inspect_mod.getsource(AgentWorkflow.__init__)
        assert "Console(stderr=True)" in src, (
            "AgentWorkflow.__init__ must construct its Console with stderr=True "
            "so the shared progress channel stays off stdout. A bare Console() "
            "writes to stdout and breaks `agac <cmd> --json | jq .`."
        )


class TestDiscoveryProgressChannel:
    """The discovery print site honors the Console it is handed."""

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
        """Given a stderr-bound Console, discovery prints the banner to
        stderr only — stdout stays clean."""
        tools = tmp_path / "tools"
        self._write_noop_udf(tools)

        console = Console(file=sys.stderr, force_terminal=False, width=120)
        _discover_udfs_from_path(str(tools), project_root=None, console=console)

        captured = capfd.readouterr()
        assert "Discovering Tools" not in captured.out, (
            "Discovery banner leaked to stdout — would break `--json | jq`.\n"
            f"stdout was: {captured.out!r}"
        )
        assert "Discovering Tools" in captured.err, (
            "Discovery banner must remain visible on stderr — humans need it.\n"
            f"stderr was: {captured.err!r}"
        )

    def test_stdout_console_demonstrates_the_bug(self, tmp_path, capfd):
        """Negative control: a stdout-bound Console DOES leak to stdout.
        If this ever stops being true, the test above is meaningless —
        re-derive the regression."""
        tools = tmp_path / "tools"
        self._write_noop_udf(tools)

        console = Console(file=sys.stdout, force_terminal=False, width=120)
        _discover_udfs_from_path(str(tools), project_root=None, console=console)

        captured = capfd.readouterr()
        assert "Discovering Tools" in captured.out, (
            "Stdout-bound Console no longer leaks discovery progress — the "
            "print site moved or was removed. Re-derive the regression."
        )
