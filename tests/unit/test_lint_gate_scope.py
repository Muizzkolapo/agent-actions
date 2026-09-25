"""Pins the ruff gate to enforcing rules in every tree that holds tracked Python.

Scope is asserted by enforcement, not discovery: asking ruff which files it would *read*
misses every narrowing that acts afterwards — ``per-file-ignores`` set to ``["ALL"]``,
``lint.exclude``, ``format.exclude``, a trimmed ``select`` — each of which leaves the file
list intact. So these tests plant a real violation in each tree and require the task's own
ruff command to report it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TASKFILE = _REPO_ROOT / "Taskfile.yml"
_CI_WORKFLOW = _REPO_ROOT / ".github/workflows/ci.yml"

_UNUSED_IMPORT = "import os\n"  # F401
_MISFORMATTED = "x  =  1\n"


def _ruff() -> str:
    candidate = Path(sys.prefix) / "bin" / "ruff"
    resolved = str(candidate) if candidate.is_file() else __import__("shutil").which("ruff")
    assert resolved, "ruff is a dev dependency and must be installed to verify the lint gate"
    return resolved


def _ruff_invocations(task_name: str) -> list[list[str]]:
    """Every argv the named task hands to ruff, Taskfile vars resolved.

    A task may split its scope across several ruff commands; that is still a wide gate, so
    the tests union what the commands report rather than demanding a single invocation.
    """
    doc = yaml.safe_load(_TASKFILE.read_text())
    task = doc["tasks"][task_name]
    assert "dir" not in task, (
        f"task {task_name!r} sets dir:, moving the gate's root out from under this test"
    )

    cmds = [c for c in task["cmds"] if isinstance(c, str) and "ruff" in c]
    assert cmds, f"task {task_name!r} runs no ruff command"

    invocations = []
    for cmd in cmds:
        for name, value in doc.get("vars", {}).items():
            cmd = cmd.replace("{{." + name + "}}", str(value))
        tokens = cmd.split()
        invocations.append(tokens[tokens.index("ruff") + 1 :])
    return invocations


def _tracked(*patterns: str) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", *patterns],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line for line in result.stdout.splitlines() if line.strip()}


def _in_scope_trees() -> set[str]:
    """Top-level directories the gate must enforce rules in, derived from the repo."""
    return {path.split("/")[0] for path in _tracked("*.py") if "/" in path}


def _plant(contents: str) -> dict[str, Path]:
    """One offending file per in-scope tree, uniquely named so parallel runs don't collide."""
    planted = {
        tree: _REPO_ROOT / tree / f"_lint_gate_probe_{uuid4().hex}.py" for tree in _in_scope_trees()
    }
    for path in planted.values():
        path.write_text(contents)
    return planted


def _report_on_planted(task_name: str, contents: str) -> tuple[bool, list[str]]:
    """Run the task's own ruff commands over a tree seeded with one bad file per subtree."""
    planted = _plant(contents)
    flagged, output = False, ""
    try:
        for args in _ruff_invocations(task_name):
            # --check keeps the writer task read-only; --no-cache so no stale verdict is reused.
            args = [a for a in args if a != "--check"]
            if args[0] == "format":
                args.insert(1, "--check")
            result = subprocess.run(
                [_ruff(), *args, "--no-cache"],
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
            )
            flagged = flagged or result.returncode != 0
            output += result.stdout
    finally:
        for path in planted.values():
            path.unlink(missing_ok=True)
    unreported = [tree for tree, path in planted.items() if path.name not in output]
    return flagged, unreported


def test_in_scope_trees_are_discovered():
    """Guards the helpers: an empty result would make every enforcement assertion vacuous."""
    assert len(_tracked("*.py")) > 500, (
        f"expected the full tracked tree, got {len(_tracked('*.py'))}"
    )
    assert _in_scope_trees() >= {"agent_actions", "examples", "tests"}


def test_lint_task_enforces_rules_in_every_in_scope_tree():
    flagged, unreported = _report_on_planted("lint", _UNUSED_IMPORT)
    assert flagged, "`task lint` reported no violation for any planted file"
    assert not unreported, f"`task lint` does not enforce rules in {sorted(unreported)}"


@pytest.mark.parametrize("task_name", ["format", "format:check"])
def test_format_task_enforces_formatting_in_every_in_scope_tree(task_name):
    flagged, unreported = _report_on_planted(task_name, _MISFORMATTED)
    assert flagged, f"`task {task_name}` reported no misformatting for any planted file"
    assert not unreported, f"`task {task_name}` does not reach {sorted(unreported)}"


def test_ci_runs_the_gate_through_the_tasks():
    """The tasks are only the gate because CI calls them; an inlined ruff bypasses them."""
    workflow = yaml.safe_load(_CI_WORKFLOW.read_text())
    runs = [
        step.get("run", "") for job in workflow["jobs"].values() for step in job.get("steps", [])
    ]
    assert "task lint" in runs, f"CI no longer runs `task lint`; it runs {runs}"
    assert "task format:check" in runs, f"CI no longer runs `task format:check`; it runs {runs}"
