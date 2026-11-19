"""`inspect` loads a workflow that includes one branch under several `as:` names."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.unit.config.test_a_workflow_includes_a_branch_file import A, _project, _with
from tests.unit.config.test_an_include_as_gives_each_instance_its_own_names import (
    REVIEW,
    WRITE,
    _round,
    _use,
)

TOOLS = "from agent_actions import udf_tool\n" + "".join(
    f"\n\n@udf_tool()\ndef {name}(data, **kwargs):\n    return {{'text': 'x'}}\n"
    for name in ("host_a", "round_write", "round_review")
)


@pytest.fixture
def inspect(tmp_path: Path, monkeypatch, isolated_user_tools):
    def run(actions, branches, folder: str) -> str:
        root = tmp_path / folder
        _project(root, actions, branches)
        (root / "tools").mkdir()
        (root / "tools" / "round_tools.py").write_text(TOOLS)
        (root / "agent_workflow" / "wf" / "agent_io" / "staging").mkdir(parents=True)
        monkeypatch.chdir(root)
        return CliRunner().invoke(cli, ["inspect", "-a", "wf"]).output

    return run


def test_inspect_reports_a_short_name_the_group_does_not_define_and_no_binding_gives(inspect):
    reader = _with(REVIEW, context_scope={"observe": ["write.text", "draft.text"]})

    output = inspect([A, _use("c"), _use("c2")], {"round": _round([WRITE, reader])}, "bad")

    assert (
        "reads 'draft', which the branch does not define and no input of include 'c' binds."
        in " ".join(output.split())
    )
    output = inspect([A, _use("c"), _use("c2")], {"round": _round()}, "good")
    assert [line.split()[1] for line in output.splitlines() if line.startswith("  ✓")] == [
        "a",
        "c2__write",
        "c__write",
        "c2__review",
        "c__review",
    ]
