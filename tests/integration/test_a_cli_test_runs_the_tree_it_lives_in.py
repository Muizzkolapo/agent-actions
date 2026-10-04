"""A test that runs `agac` runs the tree it lives in, not the installed checkout.

The console script imports `agent_actions` from wherever the venv's editable
install points, and from a second worktree that is another checkout: a CLI test
would pass or fail on that checkout's code, whatever the change under test.
pytest.ini's `pythonpath` reaches the pytest process only.
"""

import re
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "tests" / "_support" / "agac_cli.py"

# Tool discovery imports this inside the CLI process, so it sees the
# `agent_actions` that process imported.
PROBE = """\
from pathlib import Path

import agent_actions
from agent_actions import udf_tool

Path(__file__).with_name("imported_from.txt").write_text(agent_actions.__file__)


@udf_tool
def probe(data):
    return data
"""

# The console script's name as a path segment, a command's first word, or a lookup.
LAUNCH = re.compile(r"""(/\s*|\[\s*|which\(\s*)["']agac["']""")


def test_the_agac_a_test_runs_imports_agent_actions_from_this_tree(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "probe.py").write_text(PROBE)

    result = run_agac(tmp_path, "list-udfs", "-u", "tools")

    assert result.returncode == 0, result.stdout + result.stderr
    imported = Path((tools / "imported_from.txt").read_text()).resolve()
    assert imported == REPO / "agent_actions" / "__init__.py"


@pytest.mark.parametrize("handed_over", ["inherited", "passed"])
def test_a_pythonpath_already_set_stays_on_the_path_behind_this_tree(
    tmp_path, monkeypatch, handed_over
):
    """The entry is a decoy: its `agent_actions` raises on import, so the run fails
    unless this tree comes first, and the probe imports a module only it holds, so
    the run fails if the entry is dropped. A PYTHONPATH entry outranks the editable
    install, so this fails in CI too, where the install is the tree under test."""
    decoy = tmp_path / "decoy"
    (decoy / "agent_actions").mkdir(parents=True)
    (decoy / "agent_actions" / "__init__.py").write_text('raise ImportError("the decoy")\n')
    (decoy / "only_on_the_decoy_path.py").write_text("")
    project = tmp_path / "project"
    tools = project / "tools"
    tools.mkdir(parents=True)
    (tools / "probe.py").write_text("import only_on_the_decoy_path\n" + PROBE)

    if handed_over == "inherited":
        monkeypatch.setenv("PYTHONPATH", str(decoy))
        result = run_agac(project, "list-udfs", "-u", "tools")
    else:
        monkeypatch.delenv("PYTHONPATH", raising=False)
        result = run_agac(project, "list-udfs", "-u", "tools", env={"PYTHONPATH": str(decoy)})

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tools / "imported_from.txt").exists(), result.stdout + result.stderr
    imported = Path((tools / "imported_from.txt").read_text()).resolve()
    assert imported == REPO / "agent_actions" / "__init__.py"


def test_no_test_launches_agac_but_through_the_shared_launcher():
    """A launch of its own runs whichever checkout the venv points at, and passes
    wherever that checkout is the tree under test, as it is in CI."""
    launches = [
        f"{path.relative_to(REPO)}:{number}"
        for path in sorted((REPO / "tests").rglob("*.py"))
        # tests/manual is run by hand, against the `agac` on PATH.
        if path != LAUNCHER and "manual" not in path.relative_to(REPO).parts
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if LAUNCH.search(line)
    ]

    assert launches == []
