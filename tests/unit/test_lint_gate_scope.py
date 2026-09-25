"""Pins the ruff gate's effective scope to every tracked Python file.

Coverage is read back from ruff itself rather than from the Taskfile's path arguments: a
narrowing can arrive as the task's scope, an ``--exclude`` flag, or an ``exclude`` in
``pyproject.toml``, and only the first is visible in the YAML. ``--no-cache`` is load
bearing — ruff reports a cached clean result for a file it has not re-read, so a warm
cache hides a violation from every scope at once.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TASKFILE = _REPO_ROOT / "Taskfile.yml"


def _ruff() -> str:
    candidate = Path(sys.prefix) / "bin" / "ruff"
    resolved = str(candidate) if candidate.is_file() else shutil.which("ruff")
    assert resolved, "ruff is a dev dependency and must be installed to verify the lint gate"
    return resolved


def _ruff_args(task_name: str) -> list[str]:
    """The argv the named task hands to ruff, Taskfile vars resolved."""
    doc = yaml.safe_load(_TASKFILE.read_text())
    variables = doc.get("vars", {})
    cmds = [c for c in doc["tasks"][task_name]["cmds"] if isinstance(c, str) and "ruff" in c]
    assert len(cmds) == 1, f"task {task_name!r} must run exactly one ruff command, found {cmds}"

    cmd = cmds[0]
    for name, value in variables.items():
        cmd = cmd.replace("{{." + name + "}}", str(value))
    tokens = cmd.split()
    return tokens[tokens.index("ruff") + 1 :]


def _files_ruff_would_inspect(args: list[str]) -> set[str]:
    """Repo-relative paths ruff reports it would read, given a task's own arguments."""
    result = subprocess.run(
        [_ruff(), *args, "--no-cache", "--show-files"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    listed = (Path(line) for line in result.stdout.splitlines() if line.strip())
    return {str(p.relative_to(_REPO_ROOT)) if p.is_absolute() else str(p) for p in listed}


def _tracked_python_files() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line for line in result.stdout.splitlines() if line.strip()}


def _scope_tokens(task_name: str) -> set[str]:
    """A task's ruff arguments minus the subcommand, for comparing lint against format."""
    return {t for t in _ruff_args(task_name)[1:] if t != "--check"}


def test_tracked_python_files_are_discovered():
    """Guards the helpers: empty results would make the coverage assertion vacuous."""
    tracked = _tracked_python_files()
    assert len(tracked) > 500, f"expected the full tracked tree, got {len(tracked)} files"
    assert {p.split("/")[0] for p in tracked} == {"agent_actions", "examples", "tests"}


def test_lint_task_inspects_every_tracked_python_file():
    unreached = _tracked_python_files() - _files_ruff_would_inspect(_ruff_args("lint"))
    assert not unreached, (
        f"`task lint` would not read {len(unreached)} tracked file(s), e.g. {sorted(unreached)[:5]}"
    )


def test_format_tasks_carry_the_same_scope_as_lint():
    """One tree, one scope: `ruff format` has no --show-files, so compare arguments."""
    assert _scope_tokens("format") == _scope_tokens("lint")
    assert _scope_tokens("format:check") == _scope_tokens("lint")
