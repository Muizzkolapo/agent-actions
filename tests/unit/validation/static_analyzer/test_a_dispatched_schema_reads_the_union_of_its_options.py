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
    fields = {
        "topic_answer": ("topic", "shared", "note"),
        "verdict_answer": ("verdict", "shared", "note"),
        "label_answer": ("label", "shared"),
    }
    for name, ids in fields.items():
        body = "".join(f"  - id: {field}\n    type: string\n" for field in ids)
        (root / "schema" / f"{name}.yml").write_text(f"name: {name}\nfields:\n{body}")
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


def test_a_field_in_the_first_option_only_names_the_option_that_lacks_it(tmp_path):
    errors, warnings = _about(_analyze(tmp_path, "topic", OPTIONS), "'topic'")

    assert errors == []
    assert warnings == [
        "Field 'topic' of action 'label_page' is in schema_options topic_answer but not in "
        "verdict_answer; it can be absent."
    ]


def test_a_field_in_a_later_option_only_is_read_past_the_first(tmp_path):
    _, warnings = _about(_analyze(tmp_path, "verdict", OPTIONS), "'verdict'")

    assert warnings == [
        "Field 'verdict' of action 'label_page' is in schema_options verdict_answer but not in "
        "topic_answer; it can be absent."
    ]


def test_a_field_in_two_of_three_options_names_both_sides(tmp_path):
    options = ["topic_answer", "verdict_answer", "label_answer"]
    result = _analyze(tmp_path, "note", options)
    warnings = [w for w in result.warnings if "'note'" in w.message]

    assert [w.message for w in warnings] == [
        "Field 'note' of action 'label_page' is in schema_options topic_answer, verdict_answer "
        "but not in label_answer; it can be absent."
    ]
    assert warnings[0].hint == "Read it with a default, or guard the reader on the field."


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
