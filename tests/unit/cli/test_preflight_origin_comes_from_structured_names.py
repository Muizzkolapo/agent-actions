"""The `Origin:` line names an action that a message is attached to, never a word of its text."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.validation.dag_schema_fit_validator import DAG_FIT_REMEDY
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

TOOLS = (
    "from agent_actions import udf_tool\n"
    "from agent_actions.config.schema import Granularity\n"
    "from agent_actions.utils.udf_management.registry import FileUDFResult\n"
    + "".join(
        f"\n\n@udf_tool()\ndef {name}(data, **kwargs):\n    return {{'text': 'x'}}\n"
        for name in ("host_a", "pair_one", "pair_two", "host_c", "host_ab1")
    )
    + "\n\n@udf_tool(granularity=Granularity.FILE)\ndef pair_file(data):\n"
    "    return FileUDFResult(outputs=[{'source_index': 0, 'data': {'text': 'x'}}])\n"
)
B2_FROM_PAIR = "  Origin: 'b2' comes from branch 'pair' (branches/pair.yml)."


class _Warnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def inspect(tmp_path: Path, monkeypatch, isolated_user_tools):
    def run(actions, branches=None, folder: str = "included") -> tuple[str, list[str]]:
        root = tmp_path / folder
        _project(root, actions, branches)
        (root / "tools").mkdir()
        (root / "tools" / "pair_tools.py").write_text(TOOLS)
        (root / "agent_workflow" / "wf" / "agent_io" / "staging").mkdir(parents=True)
        monkeypatch.chdir(root)
        warnings = _Warnings()
        preflight = logging.getLogger("agent_actions.services.preflight_service")
        preflight.addHandler(warnings)
        try:
            output = CliRunner().invoke(cli, ["inspect", "-a", "wf"]).output
        finally:
            preflight.removeHandler(warnings)
        return output, warnings.messages

    return run


def test_each_warning_group_names_only_the_branch_of_its_own_actions(inspect):
    with_b1_field = _with(
        A,
        schema={
            "type": "object",
            "properties": {"text": {"type": "string"}, "b1": {"type": "string"}},
            "required": [],
        },
    )
    host_ab1 = {
        "name": "ab1",
        "kind": "tool",
        "impl": "host_ab1",
        "intent": "host",
        "schema": {"text": "string"},
        "dependencies": ["a"],
        "context_scope": {"observe": ["a.text", "a.b1"]},
        "guard": {"condition": "a.b1 == 5", "on_false": "filter"},
    }
    file_b1 = _with(
        B1,
        impl="pair_file",
        granularity="File",
        schema={
            "type": "object",
            "properties": {"text": {"type": "string"}, "extra": {"type": "string"}},
            "required": ["text", "extra"],
        },
    )

    _, warnings = inspect([with_b1_field, INCLUDE, host_ab1, C], {"pair": _pair([file_b1, B2])})

    assert warnings == [
        "Pre-flight: static analysis — 1 warning(s)\n"
        "  └─ ab1: Guard on action 'ab1': type mismatch in 'a.b1 == 5' — 'a.b1' is declared "
        "'string' in the schema of 'a' but the literal is number (5); the comparison outcome is "
        'decided by the types, not the data. Quote the literal (e.g. a.b1 == "5"), or change '
        "the schema type.",
        "Pre-flight: dag-fit — 1 required output field(s) a tool's code does not return, "
        "across 1 action(s)\n"
        "  ├─ b1: extra — not returned by tool 'pair_file'\n"
        f"  ├─ Fix: {DAG_FIT_REMEDY}\n"
        "  └─ Origin: 'b1' comes from branch 'pair' (branches/pair.yml).",
    ]


@pytest.mark.parametrize(
    "reader",
    [
        pytest.param({"observe": ["a.b1"]}, id="a field named like a branch action"),
        pytest.param({"guard": "zzz.text == 'x'"}, id="a hint that lists every action"),
    ],
)
def test_a_host_refusal_that_names_branch_actions_only_in_its_text_prints_as_inline(
    inspect, reader
):
    host = (
        _with(C, dependencies=["a"], context_scope={"observe": reader["observe"]})
        if "observe" in reader
        else _with(C, guard={"condition": reader["guard"], "on_false": "filter"})
    )
    reads_b2 = _with(C, context_scope={"observe": ["b2.missing"]})

    included, _ = inspect([A, INCLUDE, host])
    inline, _ = inspect([A, B1, B2, host], {}, "inline")
    positive, _ = inspect([A, INCLUDE, reads_b2], folder="positive")

    assert included == inline
    assert "Origin" not in included
    assert B2_FROM_PAIR in positive.splitlines()


@pytest.mark.parametrize(
    ("values", "first"),
    [([1, 2], "b1_1"), (["x-y", "p.q", "z"], "b1_x-y"), ([-1, 0], "b1_-1")],
)
def test_a_version_is_found_by_its_own_name(inspect, values, first):
    missing = _with(B1, impl="pair_missing", versions={"range": values})

    output, _ = inspect([A, INCLUDE], {"pair": _pair([missing], outputs=[])})

    lines = output.splitlines()
    assert f"  Action: {first}" in lines
    assert f"  Origin: '{first}' comes from branch 'pair' (branches/pair.yml)." in lines


def test_a_host_only_workflow_prints_as_the_base_branch_does(inspect):
    output, warnings = inspect([A, B1, B2, C], {}, "inline")

    assert output == (
        "\nwf   ● validated                                                       4 actions\n\n"
        "  ✓  a\n  ✓  b1\n  ✓  b2\n  ✓  c\n"
    )
    assert warnings == []


def _requires(*fields: str) -> dict:
    return {
        "type": "object",
        "properties": {name: {"type": "string"} for name in ("text", "extra")},
        "required": list(fields),
    }


def test_a_refusal_built_per_action_names_only_the_action_that_has_a_finding(inspect):
    finds = _with(B1, schema=_requires("text", "extra"))
    clean = _with(B2, schema=_requires("text"))

    output, _ = inspect([A, INCLUDE, C], {"pair": _pair([finds, clean])})

    lines = output.splitlines()
    assert any(line.startswith("  Problem: PreFlightValidationError: b1:") for line in lines)
    assert [line for line in lines if line.startswith("  Origin:")] == [
        "  Origin: 'b1' comes from branch 'pair' (branches/pair.yml)."
    ]


def test_the_branch_column_starts_after_the_longest_action_name(inspect):
    host_ab1 = {
        "name": "ab1",
        "kind": "tool",
        "impl": "host_ab1",
        "intent": "host",
        "schema": {"text": "string"},
        "dependencies": ["a"],
        "context_scope": {"observe": ["a.text"]},
    }

    output, _ = inspect([A, host_ab1, INCLUDE, C])

    assert [line for line in output.splitlines() if line.startswith("  ✓")] == [
        "  ✓  a",
        "  ✓  ab1",
        "  ✓  b1   from branch pair",
        "  ✓  b2   from branch pair",
        "  ✓  c",
    ]
