"""`agac docs` and the editor see the actions route, join and loop entries become."""

from pathlib import Path

from agent_actions.tooling.docs.parser import WorkflowParser
from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.indexer import build_index

ROUTED = """\
name: wf
description: d
actions:
  - name: classify
    kind: tool
    impl: classify
    intent: Classify
    schema: { kind: string }
  - route: router
    on: classify.kind
    cases:
      a: [on_a]
    default: [on_b]
  - name: on_a
    kind: tool
    impl: on_a
    intent: A
    schema: { text: string }
  - name: on_b
    kind: tool
    impl: on_b
    intent: B
    schema: { text: string }
  - join: joined
    of: [on_a, on_b]
  - name: after
    kind: tool
    impl: after
    intent: After
    schema: { text: string }
    dependencies: [joined]
    context_scope: { observe: [joined.text, router.case] }
"""

BRANCH = """\
branch: round_branch
description: Write, then check
inputs:
  spec: the spec
  prior: the previous check
outputs: [check]
actions:
  - name: write
    kind: tool
    impl: write
    intent: Write
    schema: { text: string }
    dependencies: [spec]
    context_scope: { observe: [spec.kind, prior.*] }
  - name: check
    kind: tool
    impl: check
    intent: Check
    schema: { passed: boolean }
    dependencies: [write]
    context_scope: { observe: [write.text] }
"""

LOOPED = """\
name: wf
description: d
actions:
  - name: classify
    kind: tool
    impl: classify
    intent: Classify
    schema: { kind: string }
  - loop: round
    include: round_branch
    max_iterations: 2
    inputs: { spec: classify }
    feedback: { prior: check }
    until: check.passed == true
    result: check
  - name: after
    kind: tool
    impl: after
    intent: After
    schema: { text: string }
    dependencies: [{read}]
    context_scope: {{ observe: [{read}.passed] }}
"""


def _project(root: Path, workflow: str) -> Path:
    config = root / "agent_workflow" / "wf" / "agent_config"
    config.mkdir(parents=True)
    (root / "agent_actions.yml").write_text("schema_path: schema\n")
    (root / "branches").mkdir()
    (root / "branches" / "round_branch.yml").write_text(BRANCH)
    path = config / "wf.yml"
    path.write_text(workflow)
    return path


def _unresolved(path: Path, root: Path) -> list[str]:
    return [
        d.message
        for d in collect_diagnostics(path, build_index(root))
        if d.message.startswith(("Unresolved action reference", "Cannot resolve"))
    ]


def _looped(read: str) -> str:
    return LOOPED.replace("{read}", read).replace("{{", "{").replace("}}", "}")


class TestTheDocsCatalog:
    def test_it_lists_the_router_and_the_join_of_a_workflow_with_no_include(self, tmp_path):
        workflow = WorkflowParser.parse_workflow(str(_project(tmp_path, ROUTED)), tmp_path)

        assert workflow is not None
        assert list(workflow["actions"]) == [
            "classify",
            "router",
            "on_a",
            "on_b",
            "joined",
            "after",
        ]
        assert workflow["actions"]["joined"]["implementation"] == "agac.pick"

    def test_it_lists_each_iteration_and_the_action_named_after_the_loop(self, tmp_path):
        workflow = WorkflowParser.parse_workflow(
            str(_project(tmp_path, _looped("round"))), tmp_path
        )

        assert workflow is not None
        assert list(workflow["actions"]) == [
            "classify",
            "round_iter1__write",
            "round_iter1__check",
            "round_iter2__write",
            "round_iter2__check",
            "round",
            "after",
        ]


class TestTheEditor:
    def test_a_read_of_a_router_and_a_join_resolves(self, tmp_path):
        path = _project(tmp_path, ROUTED)

        assert _unresolved(path, tmp_path) == []

    def test_the_router_and_the_join_point_at_their_entries(self, tmp_path):
        path = _project(tmp_path, ROUTED)
        index = build_index(tmp_path)

        router, joined = index.get_action("router", path), index.get_action("joined", path)
        assert router is not None and joined is not None
        assert (router.line, router.column) == (8, 11)
        assert (joined.line, joined.column) == (23, 10)

    def test_a_read_of_the_loop_name_resolves_and_points_at_the_loop_entry(self, tmp_path):
        path = _project(tmp_path, _looped("round"))
        index = build_index(tmp_path)

        assert _unresolved(path, tmp_path) == []
        location = index.get_action("round", path)
        assert location is not None
        assert (location.file_path, location.line) == (path, 8)

    def test_an_action_of_the_loops_branch_is_not_an_action_of_the_workflow(self, tmp_path):
        path = _project(tmp_path, _looped("check"))

        assert _unresolved(path, tmp_path) == ["Unresolved action reference `check`."]
