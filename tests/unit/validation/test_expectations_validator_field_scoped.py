"""Preflight reads a schema's rules the way the runner will, fields included."""

import yaml

from agent_actions.validation.expectations_validator import find_expectation_defects

FIELDS = {"summarize": {"summary", "exam_density"}}


def action(schema_data, name="summarize"):
    return {name: {"name": name, "schema": schema_data, "expect": {"repair": "none"}}}


def field_scoped(rules, field_id="summary"):
    return {
        "name": "fb_page_summary",
        "fields": [{"id": field_id, "type": "string", "expectations": rules}],
    }


def project(tmp_path):
    (tmp_path / "agent_actions.yml").write_text(yaml.safe_dump({"schema_path": "schema"}))
    (tmp_path / "schema").mkdir(exist_ok=True)
    return tmp_path


def test_a_bare_block_finds_the_rules_declared_on_the_fields(tmp_path):
    schema = field_scoped([{"type": "word_count_between", "params": {"min": 10, "max": 80}}])
    defects = find_expectation_defects(action(schema), FIELDS, project_root=project(tmp_path))
    assert defects == {}


def test_a_defect_in_a_field_scoped_rule_is_reported(tmp_path):
    schema = field_scoped([{"id": "bogus", "type": "vibe_check"}])
    defects = find_expectation_defects(action(schema), FIELDS, project_root=project(tmp_path))
    assert "vibe_check" in defects["summarize"][0]


def test_a_field_scoped_rule_declaring_its_own_selector_is_reported(tmp_path):
    schema = field_scoped([{"type": "not_null", "field": "exam_density"}])
    defects = find_expectation_defects(action(schema), FIELDS, project_root=project(tmp_path))
    assert "field:" in defects["summarize"][0]


def test_a_schema_with_no_rules_at_all_is_still_reported(tmp_path):
    schema = {"name": "shape_only", "fields": [{"id": "summary", "type": "string"}]}
    defects = find_expectation_defects(action(schema), FIELDS, project_root=project(tmp_path))
    assert defects["summarize"]


def test_an_inline_rule_written_with_flat_arguments_names_the_params_block():
    configs = {
        "summarize": {
            "name": "summarize",
            "expect": {"expectations": [{"type": "item_count", "field": "summary", "equals": 4}]},
        }
    }
    defects = find_expectation_defects(configs, FIELDS)
    assert "params" in defects["summarize"][0]


def test_an_inline_rule_using_the_old_severity_word_names_its_replacement():
    configs = {
        "summarize": {
            "name": "summarize",
            "expect": {
                "expectations": [
                    {"type": "not_null", "field": "summary", "severity": "fail"},
                ]
            },
        }
    }
    assert "error" in defects_for(configs)


def defects_for(configs):
    return " ".join(find_expectation_defects(configs, FIELDS).get("summarize", []))


def test_row_condition_is_accepted_as_an_argument_on_any_type():
    configs = {
        "summarize": {
            "name": "summarize",
            "expect": {
                "expectations": [
                    {
                        "type": "not_null",
                        "field": "summary",
                        "params": {"row_condition": "exam_density == 'high'"},
                    }
                ]
            },
        }
    }
    assert find_expectation_defects(configs, FIELDS) == {}


def test_an_old_shape_rule_in_a_schema_file_is_reported_like_an_inline_one(tmp_path):
    schema = field_scoped([{"id": "sized", "type": "word_count_between", "min": 10}])
    defects = find_expectation_defects(action(schema), FIELDS, project_root=project(tmp_path))
    message = " ".join(defects["summarize"])
    assert "arguments belong under params" in message
    assert "validation error for Suite" not in message
    assert "errors.pydantic.dev" not in message


def test_every_defective_rule_in_a_schema_file_is_reported_not_just_the_first(tmp_path):
    schema = field_scoped(
        [
            {"id": "first", "type": "word_count_between", "min": 10},
            {"id": "second", "type": "vibe_check"},
        ]
    )
    defects = find_expectation_defects(action(schema), FIELDS, project_root=project(tmp_path))
    message = " ".join(defects["summarize"])
    assert "first" in message
    assert "vibe_check" in message


def test_a_schema_file_defect_is_not_dressed_as_a_missing_expectations_block(tmp_path):
    schema = field_scoped([{"id": "sized", "type": "word_count_between", "min": 10}])
    defects = find_expectation_defects(action(schema), FIELDS, project_root=project(tmp_path))
    assert "declare them under a field" not in " ".join(defects["summarize"])


def test_a_defect_names_the_rule_key_it_is_about():
    configs = {
        "summarize": {
            "name": "summarize",
            "expect": {"expectations": [{"type": "not_null", "field": 42}]},
        }
    }
    message = " ".join(find_expectation_defects(configs, FIELDS)["summarize"])
    assert "field" in message


def test_a_non_string_rule_key_is_a_defect_not_a_crash():
    configs = {
        "summarize": {
            "name": "summarize",
            "expect": {"expectations": [{"type": "not_null", "field": "summary", True: 1}]},
        }
    }
    assert find_expectation_defects(configs, FIELDS)["summarize"]
