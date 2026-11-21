"""`agac inspect` and its preflight messages name the branch of each included action."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.unit.config.test_a_workflow_includes_a_branch_file import (
    B1,
    B2,
    INCLUDE,
    A,
    C,
    _pair,
    _project,
    _with,
)
from tests.unit.config.test_an_included_branch_is_checked_like_inline_actions import TALLY, VOTE

TOOLS = "from agent_actions import udf_tool\n" + "".join(
    f"\n\n@udf_tool()\ndef {name}(data, **kwargs):\n    return {{'text': 'x'}}\n"
    for name in ("host_a", "pair_one", "pair_two", "host_c", "pair_vote", "host_tally")
)
FROM_PAIR = "come from branch 'pair' (branches/pair.yml)."
B1_FROM_PAIR = "  Origin: 'b1' comes from branch 'pair' (branches/pair.yml)."
REQUIRES_EXTRA = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "extra": {"type": "string"}},
    "required": ["text", "extra"],
}


class _Warnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def project(tmp_path: Path, isolated_user_tools):
    def make(actions, branches=None, folder: str = "included") -> Path:
        root = tmp_path / folder
        _project(root, actions, branches)
        (root / "tools").mkdir()
        (root / "tools" / "pair_tools.py").write_text(TOOLS)
        (root / "agent_workflow" / "wf" / "agent_io" / "staging").mkdir(parents=True)
        return root

    return make


def _run(root: Path, monkeypatch, *args: str) -> tuple[int, list[str], list[str]]:
    monkeypatch.chdir(root)
    warnings = _Warnings()
    preflight = logging.getLogger("agent_actions.services.preflight_service")
    preflight.addHandler(warnings)
    try:
        result = CliRunner().invoke(cli, ["inspect", *args])
    finally:
        preflight.removeHandler(warnings)
    lines = [line.rstrip() for line in result.output.splitlines()]
    return result.exit_code, lines, warnings.messages


def _inspect(root: Path, monkeypatch, *args: str) -> list[str]:
    code, lines, _ = _run(root, monkeypatch, *args)
    assert code == 0, "\n".join(lines)
    return lines


def _refusal(root: Path, monkeypatch) -> list[str]:
    code, lines, _ = _run(root, monkeypatch, "-a", "wf")
    assert code != 0, "\n".join(lines)
    return lines


def _json(root: Path, monkeypatch, *args: str) -> dict:
    output = "\n".join(_inspect(root, monkeypatch, *args, "--json"))
    return json.loads(output[output.index("{") :])


def _without_origin(lines: list[str]) -> list[str]:
    return [line for line in lines if not line.startswith("  Origin:")]


class TestTheWorkflowView:
    def test_each_included_action_names_its_branch_and_host_actions_print_as_inline(
        self, project, monkeypatch
    ):
        included = _inspect(project([A, INCLUDE, C]), monkeypatch, "-a", "wf")
        inline = _inspect(project([A, B1, B2, C], folder="inline"), monkeypatch, "-a", "wf")

        assert [line for line in included if line.startswith("  ✓")] == [
            "  ✓  a",
            "  ✓  b1  from branch pair",
            "  ✓  b2  from branch pair",
            "  ✓  c",
        ]
        assert [line for line in inline if line.startswith("  ✓")] == [
            "  ✓  a",
            "  ✓  b1",
            "  ✓  b2",
            "  ✓  c",
        ]

    def test_the_count_is_the_count_of_actions_not_of_entries(self, project, monkeypatch):
        lines = _inspect(project([A, INCLUDE, C]), monkeypatch, "-a", "wf")

        title = next(line for line in lines if "validated" in line)
        assert title.endswith("4 actions")


class TestTheActionDetail:
    def test_an_included_action_shows_its_branch_and_a_host_action_does_not(
        self, project, monkeypatch
    ):
        root = project([A, INCLUDE, C])
        included = _inspect(root, monkeypatch, "action", "-a", "wf", "b1")
        host = _inspect(root, monkeypatch, "action", "-a", "wf", "a")

        assert "  Branch       pair  (branches/pair.yml)" in included
        assert [line for line in host if line.lstrip().startswith("Branch")] == []

    def test_the_json_names_the_branch_only_for_an_included_action(self, project, monkeypatch):
        root = project([A, INCLUDE, C])

        included = _json(root, monkeypatch, "action", "-a", "wf", "b1")
        host = _json(root, monkeypatch, "action", "-a", "wf", "a")

        assert included["branch"] == {"name": "pair", "file": "branches/pair.yml"}
        assert "branch" not in host


class TestTheTemplateContext:
    def test_an_included_action_shows_its_branch_and_a_host_action_does_not(
        self, project, monkeypatch
    ):
        root = project([A, INCLUDE, C])
        included = _inspect(root, monkeypatch, "context", "-a", "wf", "b2")
        host = _inspect(root, monkeypatch, "context", "-a", "wf", "c")

        assert "  Branch:  pair  (branches/pair.yml)" in included
        assert [line for line in host if line.lstrip().startswith("Branch")] == []

    def test_the_json_names_the_branch_only_for_an_included_action(self, project, monkeypatch):
        root = project([A, INCLUDE, C])

        included = _json(root, monkeypatch, "context", "-a", "wf", "b2")
        host = _json(root, monkeypatch, "context", "-a", "wf", "a")

        assert included["branch"] == {"name": "pair", "file": "branches/pair.yml"}
        assert "branch" not in host


class TestAPreflightRefusal:
    def test_a_static_type_error_in_a_branch_names_the_branch(self, project, monkeypatch):
        reader = _with(B2, context_scope={"observe": ["b1.missing"]})

        included = _refusal(project([A, INCLUDE, C], {"pair": _pair([B1, reader])}), monkeypatch)
        inline = _refusal(project([A, B1, reader, C], {}, "inline"), monkeypatch)

        assert f"  Origin: 'b1', 'b2' {FROM_PAIR}" in included
        assert "  Reference: b1.missing" in included
        assert _without_origin(included) == inline
        assert [line for line in inline if line.startswith("  Origin:")] == []

    def test_a_refusal_built_as_text_names_the_branch(self, project, monkeypatch):
        tool = _with(B1, schema=REQUIRES_EXTRA)

        included = _refusal(project([A, INCLUDE, C], {"pair": _pair([tool, B2])}), monkeypatch)
        inline = _refusal(project([A, tool, B2, C], {}, "inline"), monkeypatch)

        assert B1_FROM_PAIR in included
        assert any(line.startswith("  Problem: PreFlightValidationError: b1:") for line in inline)
        assert _without_origin(included) == inline

    def test_a_refusal_that_names_the_action_only_in_its_context(self, project, monkeypatch):
        missing = _with(B1, impl="pair_missing")

        lines = _refusal(project([A, INCLUDE, C], {"pair": _pair([missing, B2])}), monkeypatch)

        assert "  Action: b1" in lines
        assert B1_FROM_PAIR in lines

    def test_a_host_reader_of_a_branch_output_names_where_the_output_comes_from(
        self, project, monkeypatch
    ):
        reader = _with(C, context_scope={"observe": ["b2.missing"]})

        lines = _refusal(project([A, INCLUDE, reader]), monkeypatch)

        assert "  Reference: b2.missing" in lines
        assert "  Origin: 'b2' comes from branch 'pair' (branches/pair.yml)." in lines

    def test_a_refusal_that_names_no_included_action_is_unchanged(self, project, monkeypatch):
        reader = _with(C, dependencies=["a"], context_scope={"observe": ["a.missing"]})
        named = _with(B2, context_scope={"observe": ["b1.missing"]})

        with_include = _refusal(project([A, INCLUDE, reader]), monkeypatch)
        positive = _refusal(
            project([A, INCLUDE, C], {"pair": _pair([B1, named])}, "positive"), monkeypatch
        )

        assert "  Reference: a.missing" in with_include
        assert [line for line in with_include if line.startswith("  Origin:")] == []
        assert f"  Origin: 'b1', 'b2' {FROM_PAIR}" in positive

    def test_a_refusal_that_names_a_version_by_its_base_name(self, project, monkeypatch):
        reader = _with(
            TALLY,
            dependencies=["a"],
            version_consumption=None,
            context_scope={"observe": ["a.text", "vote.text"]},
        )
        branches = {"pair": _pair([VOTE], outputs=["vote"])}

        lines = _refusal(project([A, INCLUDE, reader], branches), monkeypatch)

        assert any(
            line.startswith("  Problem: PreFlightValidationError: tally: names 'vote'")
            for line in lines
        )
        assert "  Origin: 'vote' comes from branch 'pair' (branches/pair.yml)." in lines


class TestAPreflightWarning:
    def test_a_static_warning_in_a_branch_names_the_branch(self, project, monkeypatch):
        guarded = _with(B2, guard={"condition": "b1.text == 5", "on_false": "filter"})

        _, _, included = _run(
            project([A, INCLUDE, C], {"pair": _pair([B1, guarded])}), monkeypatch, "-a", "wf"
        )
        _, _, inline = _run(project([A, B1, guarded, C], {}, "inline"), monkeypatch, "-a", "wf")

        warning = next(message for message in included if "static analysis" in message)
        assert warning.splitlines()[-1] == f"  └─ Origin: 'b1', 'b2' {FROM_PAIR}"
        assert "  ├─ b2: Guard on action 'b2'" in warning
        inline_warning = next(message for message in inline if "static analysis" in message)
        assert "Origin" not in inline_warning
        assert inline_warning.splitlines()[-1].startswith("  └─ b2: Guard on action 'b2'")
