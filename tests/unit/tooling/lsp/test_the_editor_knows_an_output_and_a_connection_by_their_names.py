"""The editor reads an output's `action:` as an action and a `connection:` as a project one.

A misspelled output action or connection was only caught when `agac run` started.
"""

from pathlib import Path

from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.handlers import build_hover_content
from agent_actions.tooling.lsp.indexer import build_index
from agent_actions.tooling.lsp.models import ReferenceType
from agent_actions.tooling.lsp.resolver import get_reference_at_position, resolve_reference

PROJECT = """tool_path: [tools]
schema_path: schema
connections:
  # the warehouse
  warehouse:
    type: sqlite
    path: warehouse.db
"""

WORKFLOW = """name: wf
defaults:
  data_source:
    type: database
    connection: warehouse
    sql: SELECT id, title FROM tickets
actions:
  - name: classify
    prompt: $wf.classify
outputs:
  - action: classify
    connection: warehouse
    table: classified
  - action: clasify
    connection: warehose
    table: misspelled
"""


def _project(tmp_path: Path, project: str = PROJECT) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    workflow = root / "agent_workflow" / "wf"
    (workflow / "agent_config").mkdir(parents=True)
    (root / "agent_actions.yml").write_text(project)
    config = workflow / "agent_config" / "wf.yml"
    config.write_text(WORKFLOW)
    return root, config


def _messages(root: Path, config: Path) -> list[str]:
    return [d.message for d in collect_diagnostics(config, build_index(root))]


def test_a_misspelled_output_action_or_connection_is_reported(tmp_path: Path):
    root, config = _project(tmp_path)

    messages = _messages(root, config)

    assert "Unresolved action reference `clasify`." in messages
    assert "Unresolved connection reference `warehose`." in messages
    assert not [m for m in messages if "reference `classify`" in m or "`warehouse`" in m], messages


def test_the_references_sit_on_the_lines_that_write_them(tmp_path: Path):
    root, config = _project(tmp_path)

    references = build_index(root).references_by_file[config]
    found = {
        (r.type, r.value, r.location.line, r.location.column)
        for r in references
        if r.type in {ReferenceType.ACTION, ReferenceType.CONNECTION}
    }

    assert found == {
        (ReferenceType.CONNECTION, "warehouse", 4, 16),
        (ReferenceType.ACTION, "classify", 10, 12),
        (ReferenceType.CONNECTION, "warehouse", 11, 16),
        (ReferenceType.ACTION, "clasify", 13, 12),
        (ReferenceType.CONNECTION, "warehose", 14, 16),
    }


def test_a_connection_goes_to_where_the_project_declares_it(tmp_path: Path):
    root, config = _project(tmp_path)
    index = build_index(root)

    reference = get_reference_at_position(WORKFLOW, 11, 18)
    assert reference is not None and reference.type == ReferenceType.CONNECTION
    location = resolve_reference(reference, index, config)

    assert location is not None
    assert (location.file_path, location.line, location.column) == (
        root / "agent_actions.yml",
        4,
        2,
    )
    hover = build_hover_content(reference, index, current_file=config)
    assert hover is not None and "agent_actions.yml` at line 5" in hover


def test_an_output_action_goes_to_the_action(tmp_path: Path):
    root, config = _project(tmp_path)
    index = build_index(root)

    reference = get_reference_at_position(WORKFLOW, 10, 14)
    assert reference is not None and reference.type == ReferenceType.ACTION
    location = resolve_reference(reference, index, config)

    assert location is not None and location.line == 7


def test_an_action_key_outside_outputs_is_not_an_action_reference():
    text = "defaults:\n  action: classify\n"

    assert get_reference_at_position(text, 1, 12) is None


def test_no_connection_is_reported_while_the_project_file_does_not_parse(tmp_path: Path):
    root, config = _project(tmp_path, project="connections: [unclosed\n")

    messages = _messages(root, config)

    assert not [m for m in messages if "connection reference" in m], messages
