"""A schema named by an action must load, whether anything reads the action or not.

A missing file was treated as a schema decided at run time: an error only when another
action read a field from it, and nothing at all for a tool. The run then spent on every
action upstream and failed each record, or ran the tool with no schema checked.
"""

from __future__ import annotations

from pathlib import Path

from agent_actions.validation.static_analyzer import WorkflowStaticAnalyzer

SCHEMA = "name: {name}\nfields:\n  - id: {field}\n    type: string\n"


def _config(llm_schema: str, tool_schema: str) -> dict:
    return {
        "name": "wf",
        "actions": [
            {
                "name": "classify",
                "schema_name": llm_schema,
                "context_scope": {"observe": ["source.page_id"]},
            },
            {
                "name": "tag",
                "kind": "tool",
                "impl": "tag",
                "schema_name": tool_schema,
                "context_scope": {"observe": ["source.page_id"]},
            },
        ],
    }


def _schema_errors(root: Path, config: dict) -> list:
    (root / "agent_actions.yml").write_text("schema_path: schema\n")
    result = WorkflowStaticAnalyzer(config, project_root=root, tool_schemas={}).analyze()
    return [e for e in result.errors if e.location.config_field == "schema"]


def test_a_missing_schema_is_refused_once_per_action_that_names_it(tmp_path):
    errors = _schema_errors(tmp_path, _config("no_such_llm_schema", "no_such_tool_schema"))

    assert sorted(e.location.agent_name for e in errors) == ["classify", "tag"]
    by_action = {e.location.agent_name: e for e in errors}
    assert by_action["classify"].message.startswith(
        "Action 'classify' names schema 'no_such_llm_schema', which cannot be loaded: "
    )
    assert by_action["tag"].message.startswith(
        "Action 'tag' names schema 'no_such_tool_schema', which cannot be loaded: "
    )
    assert "no_such_tool_schema.yml" in by_action["tag"].hint


def test_the_same_actions_pass_when_their_schema_files_exist(tmp_path):
    (tmp_path / "schema").mkdir()
    for name, field in (("llm_schema", "label"), ("tool_schema", "tag")):
        (tmp_path / "schema" / f"{name}.yml").write_text(SCHEMA.format(name=name, field=field))

    assert _schema_errors(tmp_path, _config("llm_schema", "tool_schema")) == []
