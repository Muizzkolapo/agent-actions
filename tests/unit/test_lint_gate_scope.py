"""Pins the enforced ruff scope to the tree that actually holds tracked Python.

``task lint`` ran ``ruff check agent_actions`` while AGENTS.md, RELEASING.md and
``pyproject.toml``'s ``per-file-ignores`` (which carry ``examples/*`` and ``tests/*``
entries) all described a wider gate. CI runs ``task lint``, so four findings sat on
``main`` in ``examples/`` — code a user is invited to copy — for as long as the gap
existed. These tests fail if the enforced scope narrows again, if lint and format drift
apart, or if a new top-level Python tree appears that the gate does not reach.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TASKFILE = _REPO_ROOT / "Taskfile.yml"

# Tasks whose ruff invocation is a merge gate (`task check` chains lint + format:check,
# and `format` is the writer that must reach everything `format:check` inspects).
_RUFF_TASKS = ("lint", "format", "format:check")


def _ruff_scope(task_name: str) -> set[str]:
    """Path arguments the named task hands to ruff, with Taskfile vars resolved."""
    doc = yaml.safe_load(_TASKFILE.read_text())
    variables = doc.get("vars", {})
    cmds = doc["tasks"][task_name]["cmds"]

    ruff_cmds = [c for c in cmds if isinstance(c, str) and "ruff" in c]
    assert ruff_cmds, f"task {task_name!r} runs no ruff command"

    paths: set[str] = set()
    for cmd in ruff_cmds:
        for name, value in variables.items():
            cmd = cmd.replace("{{." + name + "}}", str(value))
        tokens = cmd.split()
        # Skip `uv run ruff <subcommand>`; the rest is flags and paths.
        after_subcommand = tokens[tokens.index("ruff") + 2 :]
        paths.update(t for t in after_subcommand if not t.startswith("-"))
    return paths


def _tracked_python_trees() -> set[str]:
    """Top-level directories under which git tracks at least one ``.py`` file."""
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.split("/")[0] for line in result.stdout.splitlines() if "/" in line}


def _unreached(scope: set[str], trees: set[str]) -> set[str]:
    if "." in scope:
        return set()
    return trees - scope


def test_tracked_python_trees_are_discovered():
    """Guards the helper: an empty result would make the coverage tests vacuous."""
    assert _tracked_python_trees() >= {"agent_actions", "examples", "tests"}


@pytest.mark.parametrize("task_name", _RUFF_TASKS)
def test_task_reaches_every_tracked_python_tree(task_name):
    unreached = _unreached(_ruff_scope(task_name), _tracked_python_trees())
    assert not unreached, (
        f"task {task_name} does not reach {sorted(unreached)}; "
        f"its scope is {sorted(_ruff_scope(task_name))}"
    )


def test_lint_and_format_check_share_one_scope():
    assert _ruff_scope("lint") == _ruff_scope("format:check")
