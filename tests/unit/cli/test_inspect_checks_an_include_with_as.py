"""`inspect` loads a workflow that includes one branch under several `as:` names."""

from __future__ import annotations

import json
import logging
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
READING_TOOL = (
    "\n\n@udf_tool()\ndef round_{key}(data, **kwargs):\n"
    "    return {{'text': data['{key}']['text']}}\n"
)


class _Warnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def inspect(tmp_path: Path, monkeypatch, isolated_user_tools):
    def run(
        actions, branches, folder: str, *args: str, tools: str = "", prompts: str = ""
    ) -> tuple[str, list[str]]:
        root = tmp_path / folder
        if not root.exists():
            _project(root, actions, branches)
            (root / "prompt_store" / "round.md").write_text(prompts)
            (root / "tools").mkdir()
            (root / "tools" / "round_tools.py").write_text(TOOLS + tools)
            (root / "agent_workflow" / "wf" / "agent_io" / "staging").mkdir(parents=True)
        monkeypatch.chdir(root)
        warnings = _Warnings()
        preflight = logging.getLogger("agent_actions.services.preflight_service")
        preflight.addHandler(warnings)
        try:
            output = CliRunner().invoke(cli, ["inspect", *(args or ("-a", "wf"))]).output
        finally:
            preflight.removeHandler(warnings)
        return output, warnings.messages

    return run


def _listed(output: str) -> list[str]:
    return [line.rstrip() for line in output.splitlines() if line.startswith("  ✓")]


def test_inspect_reports_a_short_name_the_group_does_not_define_and_no_binding_gives(inspect):
    reader = _with(REVIEW, context_scope={"observe": ["write.text", "draft.text"]})

    output, _ = inspect([A, _use("c"), _use("c2")], {"round": _round([WRITE, reader])}, "bad")

    assert (
        "reads 'draft', which the branch does not define and no input of include 'c' binds."
        in " ".join(output.split())
    )
    output, _ = inspect([A, _use("c"), _use("c2")], {"round": _round()}, "good")
    assert [line.split()[1] for line in _listed(output)] == [
        "a",
        "c2__write",
        "c__write",
        "c2__review",
        "c__review",
    ]


def test_the_workflow_view_names_the_instance_of_each_action(inspect):
    output, _ = inspect([A, _use("c"), _use("c2")], {"round": _round()}, "view")

    assert _listed(output) == [
        "  ✓  a",
        "  ✓  c2__write   from branch round as c2",
        "  ✓  c__write    from branch round as c",
        "  ✓  c2__review  from branch round as c2",
        "  ✓  c__review   from branch round as c",
    ]


def test_the_action_detail_shows_the_name_map_of_its_instance(inspect):
    branches = {"round": _round()}
    actions = [A, _use("c"), _use("c2")]
    output, _ = inspect(actions, branches, "detail", "action", "-a", "wf", "c2__review")
    lines = [line.rstrip() for line in output.splitlines()]

    assert "  Branch       round as c2  (branches/round.yml)" in lines
    assert "  Names        write → c2__write, review → c2__review, spec → a" in lines

    output, _ = inspect(actions, branches, "detail", "action", "-a", "wf", "c2__review", "--json")
    assert json.loads(output[output.index("{") :])["branch"] == {
        "name": "round",
        "file": "branches/round.yml",
        "instance": "c2",
        "names": {"write": "c2__write", "review": "c2__review", "spec": "a"},
    }


def test_a_tool_reading_a_short_name_of_its_instance_is_no_unknown_bus_namespace(inspect):
    reader = _with(REVIEW, impl="round_write")
    branch = {"round": _round([_with(WRITE, impl="round_spec"), reader])}
    tools = READING_TOOL.format(key="spec") + READING_TOOL.format(key="draft")

    _, warnings = inspect([A, _use("c2")], branch, "short", tools=tools)
    assert not any("bus namespace" in message for message in warnings), warnings

    unknown = {"round": _round([_with(WRITE, impl="round_draft"), reader])}
    _, warnings = inspect([A, _use("c2")], unknown, "unknown", tools=tools)
    assert any("reads bus namespace 'draft'" in message for message in warnings), warnings


def test_a_prompt_reading_a_short_name_it_does_not_observe_is_reported_by_its_action(inspect):
    judge = {
        "name": "judge",
        "intent": "judge",
        "prompt": "$round.Judge",
        "schema": {"verdict": "string"},
        "dependencies": ["write"],
        "context_scope": {"observe": ["spec.text"]},
    }
    prompts = "{prompt Judge}\nJudge {{ write.text }} against {{ spec.text }}.\n{end_prompt}\n"
    branch = {"round": _round([WRITE, judge], outputs=["judge"])}

    output, _ = inspect([A, _use("c2")], branch, "unobserved", prompts=prompts)

    assert (
        "Action 'c2__judge': template references namespace 'c2__write' which is not declared "
        "in context_scope.observe or passthrough." in " ".join(output.split())
    ), output
