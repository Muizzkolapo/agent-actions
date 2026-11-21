"""Every command and subcommand shows its --help in a folder that is not a project (1730).

`agac docs test --help` stopped with ProjectNotFoundError: the `docs` group checked for a
project in its callback, which Click runs before a subcommand reads its --help.
"""

from __future__ import annotations

import click
import pytest

from agent_actions.cli.main import CLI
from tests._support.agac_cli import run_agac


def _command_paths(group: click.Group, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    for name, command in sorted(group.commands.items()):
        path = (*prefix, name)
        paths.append(path)
        if isinstance(command, click.Group):
            paths.extend(_command_paths(command, path))
    return paths


COMMANDS = _command_paths(CLI().click_group)


def test_the_walk_finds_the_docs_test_subcommand():
    assert ("docs", "test") in COMMANDS


@pytest.mark.parametrize("path", COMMANDS, ids=[" ".join(p) for p in COMMANDS])
def test_help_works_outside_a_project(tmp_path, path):
    result = run_agac(tmp_path, *path, "--help")

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Usage:" in output, output
    assert "ProjectNotFoundError" not in output, output


def test_the_docs_group_still_needs_a_project_when_it_runs(tmp_path):
    result = run_agac(tmp_path, "docs")

    assert result.returncode == 1
    assert "Project not found" in result.stdout + result.stderr
