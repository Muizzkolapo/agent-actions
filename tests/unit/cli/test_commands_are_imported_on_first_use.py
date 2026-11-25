"""`agac --help` lists every command without importing one; a command is imported when used.

The listing shortens a command not yet imported from its summary in `_COMMANDS`, so each
summary must shorten as the command's own help does, at every width.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import click
import pytest
from click.shell_completion import ShellComplete
from click.testing import CliRunner
from click.utils import make_default_short_help

from agent_actions.cli.main import _COMMANDS, CLI

REPO = Path(__file__).resolve().parents[3]

EVERY_COMMAND = [
    "batch",
    "clean",
    "dispositions",
    "docs",
    "example",
    "expect",
    "export",
    "init",
    "inspect",
    "list-udfs",
    "preview",
    "records",
    "retry",
    "run",
    "sandbox",
    "schema",
    "skills",
    "status",
    "traces",
    "usage",
    "validate-udfs",
]


def _new_group() -> click.Group:
    with mock.patch.object(CLI, "_register_signal_handlers"):
        return CLI().click_group


def _imported(name: str) -> click.Command:
    module_name, attribute = _COMMANDS[name][0].split(":")
    return getattr(importlib.import_module(module_name), attribute)


def _eager_group() -> click.Group:
    """The group as built before commands were imported lazily: every command added."""
    group = _new_group()
    eager = click.Group(name=group.name, callback=group.callback, params=group.params)
    eager.help = group.help
    for name in _COMMANDS:
        eager.add_command(_imported(name))
    return eager


def _listing(group: click.Group, width: int) -> str:
    formatter = click.HelpFormatter(width=width)
    group.format_commands(click.Context(group), formatter)
    return formatter.getvalue()


def test_the_lazy_list_is_every_command():
    group = _new_group()
    ctx = click.Context(group)

    assert group.list_commands(ctx) == EVERY_COMMAND
    assert group.commands == {}
    for name in EVERY_COMMAND:
        command = group.get_command(ctx, name)
        assert command is _imported(name)
        assert command.name == name
    assert set(group.commands) == set(EVERY_COMMAND)


@pytest.mark.parametrize("name", EVERY_COMMAND)
def test_a_summary_shortens_as_the_command_help_does(name):
    command = _imported(name)
    summary = _COMMANDS[name][1]

    assert not command.hidden
    for limit in range(1, 200):
        assert make_default_short_help(summary, limit) == command.get_short_help_str(limit)


@pytest.mark.parametrize("width", [30, 50, 80, 120, 200])
def test_the_listing_is_the_eager_listing(width):
    assert _listing(_new_group(), width) == _listing(_eager_group(), width)


@pytest.mark.parametrize("width", [50, 80])
def test_the_listing_is_the_same_with_a_command_imported(width):
    group = _new_group()
    group.get_command(click.Context(group), "retry")

    assert _listing(group, width) == _listing(_eager_group(), width)


def test_the_full_help_is_the_eager_help():
    lazy = CliRunner().invoke(_new_group(), ["--help"], terminal_width=80)
    eager = CliRunner().invoke(_eager_group(), ["--help"], terminal_width=80)

    assert lazy.exit_code == eager.exit_code == 0
    assert lazy.output == eager.output


def test_an_unknown_command_is_refused_as_before():
    result = CliRunner().invoke(_new_group(), ["nosuch"])

    assert result.exit_code == 2
    assert "No such command 'nosuch'." in result.output


def test_completion_offers_every_command_with_its_help():
    def completions(group: click.Group) -> list[tuple[str, str | None]]:
        complete = ShellComplete(group, {}, "agent-actions", "_AGENT_ACTIONS_COMPLETE")
        return [(c.value, c.help) for c in complete.get_completions([], "")]

    assert completions(_new_group()) == completions(_eager_group())
    assert [value for value, _help in completions(_new_group())] == EVERY_COMMAND


def test_help_imports_no_command_in_a_fresh_interpreter(tmp_path):
    probe = (
        "import json, sys\n"
        "from agent_actions.cli.main import CLI\n"
        "code = CLI().execute(['--help'])\n"
        "print(json.dumps({'code': code, 'modules': sorted(sys.modules)}))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
    assert report["code"] == 0
    assert "agent_actions.expectations.registry" not in report["modules"]
    command_modules = {path.split(":")[0] for path, _summary in _COMMANDS.values()}
    assert command_modules.isdisjoint(report["modules"])
