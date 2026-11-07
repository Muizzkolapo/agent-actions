"""A dispatched schema writes one of its `schema_options`; its readers are checked against all.

A field in every option is a checked read. A field in some options can be absent, so a
reader of it is warned. A field in no option is an error. An option with no file is
refused by its own name, before any action runs.
"""

from __future__ import annotations

from pathlib import Path

from agent_actions.validation.static_analyzer import WorkflowStaticAnalyzer


def _analyze(root: Path, reads: str, options: list[str]):
    (root / "agent_actions.yml").write_text("schema_path: schema\n")
    (root / "schema").mkdir(exist_ok=True)
    for name, field in (("topic_answer", "topic"), ("verdict_answer", "verdict")):
        (root / "schema" / f"{name}.yml").write_text(
            f"name: {name}\nfields:\n  - id: {field}\n    type: string\n"
            "  - id: shared\n    type: string\n"
        )
    config = {
        "name": "wf",
        "actions": [
            {
                "name": "label_page",
                "schema": "dispatch_task('pick_schema')",
                "schema_options": options,
                "context_scope": {"observe": ["source.page_id"]},
            },
            {
                "name": "reader",
                "dependencies": ["label_page"],
                "schema": {"out": "string"},
                "context_scope": {"observe": [f"label_page.{reads}"]},
            },
        ],
    }
    return WorkflowStaticAnalyzer(config, project_root=root, tool_schemas={}).analyze()


def _about(result, field: str):
    errors = [e.message for e in result.errors if field in e.message]
    warnings = [w.message for w in result.warnings if field in w.message]
    return errors, warnings


OPTIONS = ["topic_answer", "verdict_answer"]


def test_a_field_in_every_option_is_a_checked_read(tmp_path):
    assert _about(_analyze(tmp_path, "shared", OPTIONS), "'shared'") == ([], [])


def test_a_field_in_some_options_is_warned_as_possibly_absent(tmp_path):
    errors, warnings = _about(_analyze(tmp_path, "topic", OPTIONS), "'topic'")

    assert errors == []
    assert warnings == [
        "Field 'topic' of action 'label_page' is not in every schema in its schema_options; "
        "it can be absent."
    ]


def test_a_field_in_no_option_is_an_error(tmp_path):
    errors, _ = _about(_analyze(tmp_path, "nowhere", OPTIONS), "nowhere")

    assert errors


def test_an_option_with_no_file_is_refused_by_its_name(tmp_path):
    result = _analyze(tmp_path, "shared", ["topic_answer", "no_such_option"])

    on_schema = [e for e in result.errors if e.location.config_field == "schema"]
    assert [e.location.agent_name for e in on_schema] == ["label_page"]
    assert on_schema[0].message.startswith(
        "Action 'label_page' names schema 'no_such_option', which cannot be loaded: "
    )
