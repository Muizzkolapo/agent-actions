"""The docs fallback and the editor see an included branch as the load does."""

from pathlib import Path

from agent_actions.tooling.docs.parser import WorkflowParser
from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.indexer import build_index
from tests.unit.config.test_a_workflow_includes_a_branch_file import (
    INCLUDE,
    A,
    C,
    _project,
    _with,
)


def _docs(root: Path, actions, branches=None):
    workflow = _project(root, actions, branches)
    return WorkflowParser.parse_workflow(str(workflow), root)


HOST = """name: wf
description: d
actions:
  - name: a
    kind: tool
    impl: host_a
    intent: host first
    schema: {{ text: string }}
  - include: pair
    inputs: {{ a: a }}
  - name: c
    kind: tool
    impl: host_c
    intent: host last
    schema: {{ text: string }}
    dependencies: [{read}]
    context_scope: {{ observe: [{read}.text] }}
"""


def _unresolved(root: Path, read: str) -> list[str]:
    workflow = _project(root, [A, INCLUDE])
    workflow.write_text(HOST.format(read=read))
    return [
        d.message
        for d in collect_diagnostics(workflow, build_index(root))
        if d.message.startswith(("Unresolved action reference", "Cannot resolve"))
    ]


class TestTheDocsFallback:
    def test_it_lists_the_branch_actions_in_place_of_the_include(self, tmp_path):
        workflow = _docs(tmp_path, [A, INCLUDE, C])

        assert workflow is not None
        assert list(workflow["actions"]) == ["a", "b1", "b2", "c"]

    def test_it_leaves_out_a_workflow_the_load_refuses(self, tmp_path, capsys):
        workflow = _docs(tmp_path / "bad", [A, {"include": "pairr", "inputs": {"a": "a"}}])

        assert workflow is None
        assert "is left out: the load refuses it - Include 'pairr' in" in capsys.readouterr().out
        assert _docs(tmp_path / "good", [A, INCLUDE]) is not None


class TestTheEditor:
    def test_a_host_read_of_a_branch_output_resolves(self, tmp_path):
        assert _unresolved(tmp_path, "b2") == []

    def test_a_read_of_a_name_nothing_defines_is_still_flagged(self, tmp_path):
        assert _unresolved(tmp_path, "nope") == [
            "Unresolved action reference `nope`.",
        ]

    def test_a_branch_action_that_is_not_an_output_stays_undefined(self, tmp_path):
        assert _unresolved(tmp_path, "b1") == [
            "Unresolved action reference `b1`.",
        ]

    def test_the_output_points_at_the_branch_file(self, tmp_path):
        _project(tmp_path, [A, INCLUDE, C])

        location = build_index(tmp_path).get_action(
            "b2", tmp_path / "agent_workflow" / "wf" / "agent_config" / "wf.yml"
        )

        assert location is not None
        assert location.file_path == tmp_path / "branches" / "pair.yml"
        assert location.line == 18


class TestTheDocsFallbackMakesTheLoadChecks:
    def test_a_host_read_of_a_branch_internal_is_left_out(self, tmp_path, capsys):
        reader = _with(C, dependencies=["b1"], context_scope={"observe": ["b1.text"]})

        assert _docs(tmp_path / "bad", [A, INCLUDE, reader]) is None
        assert (
            "is left out: the load refuses it - Action 'c' in agent_workflow/wf/agent_config/"
            "wf.yml reads 'b1'" in capsys.readouterr().out
        )
        assert _docs(tmp_path / "good", [A, INCLUDE, C]) is not None

    def test_a_written_origin_in_a_workflow_with_no_include_is_left_out(self, tmp_path, capsys):
        written = _with(A, _include={"branch": "pair"})

        assert _docs(tmp_path / "bad", [written], {}) is None
        assert "'_include' is set by the load" in capsys.readouterr().out
        assert _docs(tmp_path / "good", [A], {}) is not None

    def test_a_rendered_file_keeps_its_origin(self, tmp_path):
        workflow = _project(tmp_path, [_with(A, _include={"branch": "pair"})], {})

        parsed = WorkflowParser.parse_workflow(str(workflow), tmp_path, rendered=True)

        assert parsed is not None
        assert list(parsed["actions"]) == ["a"]
