"""Suite loading through the schema route and from inline lists."""

import pytest
import yaml

from agent_actions.expectations import loader
from agent_actions.expectations.loader import build_inline_suite, load_named_suite

EXPECTATIONS = [
    {"id": "option_count", "type": "item_count", "field": "options", "equals": 4},
    {
        "id": "says_the_source",
        "type": "no_forbidden_phrases",
        "field": "answer_explanation",
        "phrases": ["the source"],
        "hint": "Use 'the documentation' or state facts directly",
    },
]

SCHEMA_FIELDS = [{"id": "options", "type": "array", "items": {"type": "string"}}]


def project(tmp_path, schema_data, name="scenario_question", where="schema"):
    (tmp_path / "agent_actions.yml").write_text(yaml.safe_dump({"schema_path": "schema"}))
    schema_dir = tmp_path / where
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / f"{name}.yml").write_text(yaml.safe_dump(schema_data))
    return tmp_path


def test_load_named_suite_reads_the_expectations_block_of_a_schema_file(tmp_path):
    root = project(tmp_path, {"fields": SCHEMA_FIELDS, "expectations": EXPECTATIONS})
    suite = load_named_suite("scenario_question", project_root=root)
    assert suite.name == "scenario_question"
    assert [e.resolved_id for e in suite.expectations] == ["option_count", "says_the_source"]
    assert suite.expectations[0].params() == {"equals": 4}
    assert suite.expectations[1].hint.startswith("Use 'the documentation'")


def test_load_named_suite_accepts_a_rules_only_file(tmp_path):
    root = project(tmp_path, {"expectations": EXPECTATIONS})
    suite = load_named_suite("scenario_question", project_root=root)
    assert suite.name == "scenario_question"
    assert len(suite.expectations) == 2


def test_load_named_suite_resolves_workflow_level_schema_dirs(tmp_path):
    root = project(
        tmp_path,
        {"expectations": EXPECTATIONS},
        where="agent_workflow/quiz_gen/schema",
    )
    suite = load_named_suite("scenario_question", project_root=root)
    assert suite.name == "scenario_question"


def test_load_named_suite_missing_schema_raises_file_not_found(tmp_path):
    root = project(tmp_path, {"expectations": EXPECTATIONS})
    with pytest.raises(FileNotFoundError, match="nothing_here"):
        load_named_suite("nothing_here", project_root=root)


def test_load_named_suite_without_expectations_block_is_an_error(tmp_path):
    root = project(tmp_path, {"fields": SCHEMA_FIELDS})
    with pytest.raises(ValueError, match="no expectations"):
        load_named_suite("scenario_question", project_root=root)


def test_build_suite_from_schema_data_ignores_schema_shape_keys():
    data = {
        "fields": SCHEMA_FIELDS,
        "required_by_default": True,
        "expectations": EXPECTATIONS,
    }
    suite = loader.build_suite_from_schema_data("scenario_question", data)
    assert suite.name == "scenario_question"
    assert [e.resolved_id for e in suite.expectations] == ["option_count", "says_the_source"]


def test_build_suite_from_schema_data_rejects_empty_expectations():
    with pytest.raises(ValueError, match="no expectations"):
        loader.build_suite_from_schema_data("empty", {"expectations": []})


def test_build_suite_from_schema_data_rejects_non_mapping_data():
    with pytest.raises(ValueError, match="mapping"):
        loader.build_suite_from_schema_data("hollow", None)


def test_build_inline_suite_names_itself_after_the_action():
    suite = build_inline_suite(
        [{"type": "item_count", "field": "ideas", "min": 5}], action_name="brainstorm"
    )
    assert suite.name == "brainstorm:inline"
    assert suite.expectations[0].resolved_id.startswith("item_count_")
