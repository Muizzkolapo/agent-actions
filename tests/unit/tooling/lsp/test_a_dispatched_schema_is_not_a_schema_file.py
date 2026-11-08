"""The editor tells a ``schema: dispatch_task('fn')`` from a schema file name as the run does.

Its own pattern took ``dispatch_task`` for a schema file, so a value ``agac inspect``
accepts showed as an unresolved schema.
"""

from pathlib import Path

from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.indexer import build_index
from agent_actions.tooling.lsp.models import ReferenceType


def _project(tmp_path: Path, schema_lines: str) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    workflow = root / "agent_workflow" / "wf"
    (workflow / "agent_config").mkdir(parents=True)
    (root / "agent_actions.yml").write_text("tool_path: [tools]\nschema_path: schema\n")
    (root / "tools").mkdir()
    (root / "tools" / "pick_schema.py").write_text("def pick_schema(record):\n    return 'short'\n")
    (root / "schema" / "wf").mkdir(parents=True)
    (root / "schema" / "wf" / "short.yml").write_text("name: short\nfields: []\n")
    config = workflow / "agent_config" / "wf.yml"
    config.write_text(
        f"name: wf\nactions:\n  - name: answer\n    prompt: $wf.answer\n{schema_lines}"
    )
    return root, config


def _schema_diagnostics(root: Path, config: Path) -> list[str]:
    index = build_index(root)
    return [d.message for d in collect_diagnostics(config, index) if "schema" in d.message]


def test_a_dispatch_call_is_not_flagged_as_an_unresolved_schema(tmp_path: Path):
    root, config = _project(
        tmp_path,
        "    schema: dispatch_task('pick_schema')  # chosen per record\n"
        "    schema_options: [short]\n",
    )

    assert _schema_diagnostics(root, config) == []


def test_a_dispatch_call_records_no_schema_reference(tmp_path: Path):
    root, config = _project(tmp_path, '    schema: dispatch_task("pick_schema")\n')

    index = build_index(root)

    assert index.file_actions[config]["answer"].schema_ref is None
    assert not [r for r in index.references_by_file[config] if r.type == ReferenceType.SCHEMA]


def test_a_missing_schema_file_is_still_flagged(tmp_path: Path):
    root, config = _project(tmp_path, "    schema: no_such_schema\n")

    assert _schema_diagnostics(root, config) == ["Unresolved schema reference `no_such_schema`."]


def test_a_schema_file_named_like_the_call_is_still_a_reference(tmp_path: Path):
    root, config = _project(tmp_path, "    schema: dispatch_tasks\n")

    assert _schema_diagnostics(root, config) == ["Unresolved schema reference `dispatch_tasks`."]


def test_a_schema_file_that_exists_resolves(tmp_path: Path):
    root, config = _project(tmp_path, "    schema: short\n")

    assert _schema_diagnostics(root, config) == []
