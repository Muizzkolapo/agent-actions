"""A test that runs `agac` runs the tree it lives in, not the installed checkout.

The console script imports `agent_actions` from wherever the venv's editable
install points, and from a second worktree that is another checkout: a CLI test
would pass or fail on that checkout's code, whatever the change under test.
pytest.ini's `pythonpath` reaches the pytest process only.
"""

import ast
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "tests" / "_support" / "agac_cli.py"
AUDIT = Path(__file__).resolve()
# Reads the `agac` commands the docs' code blocks show as text, and walks the
# command tree in-process: it names the program but launches nothing.
DOCS_CHECK = REPO / "tests" / "unit" / "cli" / "test_a_documented_command_exists.py"
MANUAL = REPO / "tests" / "manual"

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

LAUNCH_NAMES = {"agac", "agent_actions.cli.main"}


def launches_in(source: str) -> list[int]:
    """Lines of *source* that name the console script or its module.

    A string that is exactly one of them counts wherever it sits (a path
    segment, a command's element, a lookup, `-m`), and so does a command line
    starting with `agac` handed to a call, as a shell launch is.
    """
    lines: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and node.value in LAUNCH_NAMES:
            lines.add(node.lineno)
        elif isinstance(node, ast.Call) and _first_word(_command(node)) == "agac":
            lines.add(node.lineno)
    return sorted(lines)


def _command(call: ast.Call) -> ast.expr | None:
    if call.args:
        return call.args[0]
    return next((kw.value for kw in call.keywords if kw.arg == "args"), None)


def _first_word(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.JoinedStr) and node.values:
        node = node.values[0]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return next(iter(node.value.split()), None)
    return None


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


@pytest.mark.parametrize(
    "launch",
    [
        pytest.param('run([str(Path(sys.executable).parent / "agac"), "x"])', id="path segment"),
        pytest.param('run([str(Path(sys.executable).with_name("agac")), "x"])', id="sibling name"),
        pytest.param('run(["agac", "x"])', id="list element"),
        pytest.param('run(\n    [\n        "agac",\n        "x",\n    ]\n)', id="wrapped list"),
        pytest.param('run([shutil.which("agac"), "x"])', id="lookup"),
        pytest.param('run([sys.executable, "-m", "agent_actions.cli.main", "x"])', id="module"),
        pytest.param('run("agac run -a wf", shell=True)', id="shell string"),
        pytest.param('run(f"agac run -a {wf}", shell=True)', id="shell f-string"),
        pytest.param('run(args="agac run -a wf", shell=True)', id="shell string by keyword"),
    ],
)
def test_the_audit_sees_agac_launched_as_a(launch):
    """The audit passes when it finds nothing, so it is shown finding each shape."""
    assert launches_in(launch) != []


def test_no_test_launches_agac_but_through_the_shared_launcher():
    """A launch of its own runs whichever checkout the venv points at, and passes
    wherever that checkout is the tree under test, as it is in CI."""
    launches = [
        f"{path.relative_to(REPO)}:{line}"
        for path in sorted((REPO / "tests").rglob("*.py"))
        # This file and the docs check name what they look for; tests/manual
        # is run by hand, against the `agac` on PATH.
        if path not in (LAUNCHER, AUDIT, DOCS_CHECK) and not path.is_relative_to(MANUAL)
        for line in launches_in(path.read_text())
    ]

    assert launches == []
