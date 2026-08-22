"""Suite loading from files, inline lists, and project path resolution."""

import pytest
import yaml

from agent_actions.config.path_config import get_expectations_path
from agent_actions.expectations.loader import (
    SuiteNotFoundError,
    build_inline_suite,
    load_suite_file,
    suite_file_path,
)

SUITE_YAML = {
    "name": "scenario_question",
    "expectations": [
        {"id": "option_count", "type": "item_count", "field": "options", "equals": 4},
        {
            "id": "says_the_source",
            "type": "no_forbidden_phrases",
            "field": "answer_explanation",
            "phrases": ["the source"],
            "hint": "Use 'the documentation' or state facts directly",
        },
    ],
}


def test_load_suite_file_reads_name_and_expectations(tmp_path):
    path = tmp_path / "scenario_question.yml"
    path.write_text(yaml.safe_dump(SUITE_YAML))
    suite = load_suite_file(path)
    assert suite.name == "scenario_question"
    assert [e.resolved_id for e in suite.expectations] == ["option_count", "says_the_source"]
    assert suite.expectations[0].params() == {"equals": 4}
    assert suite.expectations[1].hint.startswith("Use 'the documentation'")


def test_load_suite_file_raises_when_absent(tmp_path):
    with pytest.raises(SuiteNotFoundError, match="nothing_here"):
        load_suite_file(tmp_path / "nothing_here.yml")


def test_load_suite_file_rejects_a_suite_with_no_expectations(tmp_path):
    path = tmp_path / "empty.yml"
    path.write_text(yaml.safe_dump({"name": "empty", "expectations": []}))
    with pytest.raises(ValueError):
        load_suite_file(path)


def test_build_inline_suite_names_itself_after_the_action():
    suite = build_inline_suite(
        [{"type": "item_count", "field": "ideas", "min": 5}], action_name="brainstorm"
    )
    assert suite.name == "brainstorm:inline"
    assert suite.expectations[0].resolved_id.startswith("item_count_")


def test_get_expectations_path_defaults_when_key_absent(tmp_path):
    (tmp_path / "agent_actions.yml").write_text(yaml.safe_dump({"schema_path": "schema"}))
    assert get_expectations_path(tmp_path) == "expectations"


def test_get_expectations_path_honours_an_explicit_key(tmp_path):
    (tmp_path / "agent_actions.yml").write_text(
        yaml.safe_dump({"schema_path": "schema", "expectations_path": "quality_rules"})
    )
    assert get_expectations_path(tmp_path) == "quality_rules"


def test_get_expectations_path_defaults_when_no_project_config(tmp_path):
    assert get_expectations_path(tmp_path) == "expectations"


def test_suite_file_path_nests_by_workflow(tmp_path):
    (tmp_path / "agent_actions.yml").write_text(yaml.safe_dump({"schema_path": "schema"}))
    path = suite_file_path(tmp_path, "quiz_gen", "scenario_question")
    assert path == tmp_path / "expectations" / "quiz_gen" / "scenario_question.yml"
