"""The editor reads the name of a `- route:` or `- join:` entry as the action the load makes.

An action that depended on a join showed "Unresolved action reference" in the editor, and
`impl: agac.route` showed as an unresolved tool.
"""

from pathlib import Path

from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.indexer import build_index

WORKFLOW = """name: wf
actions:
  - name: classify
    prompt: $wf.classify
  - route: router
    on: classify.kind
    cases:
      a: [on_a]
    default: filter
  - name: on_a
    prompt: $wf.answer
  - join: joined
    of: [on_a]
  - name: publish
    prompt: $wf.answer
    dependencies: [joined, router]
"""


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    workflow = root / "agent_workflow" / "wf"
    (workflow / "agent_config").mkdir(parents=True)
    (root / "agent_actions.yml").write_text("tool_path: [tools]\nschema_path: schema\n")
    config = workflow / "agent_config" / "wf.yml"
    config.write_text(WORKFLOW)
    return root, config


def test_a_dependency_on_a_join_or_a_router_is_not_unresolved(tmp_path: Path):
    root, config = _project(tmp_path)

    messages = [d.message for d in collect_diagnostics(config, build_index(root))]

    assert not [m for m in messages if "joined" in m or "router" in m], messages


def test_the_join_and_the_router_are_indexed_where_their_entries_are_written(tmp_path: Path):
    root, config = _project(tmp_path)

    actions = build_index(root).file_actions[config]

    assert actions["router"].location.line == 4
    assert actions["joined"].location.line == 11
    assert actions["joined"].dependencies == ["on_a"]
    assert actions["router"].dependencies == ["classify"]
