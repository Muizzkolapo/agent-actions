"""Preflight defect detection for expect blocks."""

import yaml

from agent_actions.validation.expectations_validator import find_expectation_defects

FIELDS = {"write_q": {"options", "answer", "answer_explanation"}}


def config(expectations, name="write_q"):
    return {name: {"name": name, "expect": {"expectations": expectations}}}


def suite_config(suite_name, name="write_q"):
    return {name: {"name": name, "expect": {"suite": suite_name}}}


def default_config(name="write_q", **action_keys):
    return {name: {"name": name, "expect": {"repair": "none"}, **action_keys}}


def write_schema_file(tmp_path, name, data):
    (tmp_path / "agent_actions.yml").write_text(yaml.safe_dump({"schema_path": "schema"}))
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir(exist_ok=True)
    (schema_dir / f"{name}.yml").write_text(yaml.safe_dump(data))


def write_suite(tmp_path, suite_name, expectations):
    write_schema_file(tmp_path, suite_name, {"expectations": expectations})


def test_clean_suite_reports_no_defects():
    defects = find_expectation_defects(
        config([{"type": "item_count", "field": "options", "params": {"equals": 4}}]), FIELDS
    )
    assert defects == {}


def test_unregistered_type_is_reported_with_the_type_name():
    defects = find_expectation_defects(config([{"type": "vibe_check", "field": "options"}]), FIELDS)
    assert "vibe_check" in defects["write_q"][0]


def test_unknown_parameter_is_reported():
    defects = find_expectation_defects(
        config([{"type": "item_count", "field": "options", "params": {"equalz": 4}}]), FIELDS
    )
    assert "equalz" in defects["write_q"][0]


def test_missing_required_parameter_is_reported():
    defects = find_expectation_defects(
        config([{"type": "word_count_ratio", "field": "options"}]), FIELDS
    )
    assert "max_ratio" in defects["write_q"][0]


def test_field_absent_from_the_action_output_is_reported():
    defects = find_expectation_defects(
        config([{"type": "not_null", "field": "nonexistent"}]), FIELDS
    )
    assert "nonexistent" in defects["write_q"][0]


def test_wildcard_selector_is_checked_against_its_base_name():
    defects = find_expectation_defects(
        config([{"type": "word_count_between", "field": "nonexistent[*]", "params": {"max": 5}}]),
        FIELDS,
    )
    assert "nonexistent" in defects["write_q"][0]


def test_list_selector_reports_only_the_absent_member():
    defects = find_expectation_defects(
        config([{"type": "not_null", "field": ["options", "ghost"]}]), FIELDS
    )
    assert "ghost" in defects["write_q"][0]
    assert "options" not in defects["write_q"][0]


def test_an_expect_field_in_the_action_output_collides_with_the_verdict_key():
    defects = find_expectation_defects(
        {
            "write_q": {
                "name": "write_q",
                "expect": {"expectations": [{"type": "not_null", "field": "options"}]},
            }
        },
        {"write_q": {"options", "expect"}},
    )
    assert any("expect" in message for message in defects["write_q"])


def test_actions_without_an_expect_block_are_skipped():
    assert find_expectation_defects({"other": {"name": "other"}}, FIELDS) == {}


def test_field_check_is_skipped_when_the_action_has_no_known_fields():
    defects = find_expectation_defects(config([{"type": "not_null", "field": "anything"}]), {})
    assert defects == {}


def test_multiple_defects_on_one_action_are_all_reported():
    defects = find_expectation_defects(
        config(
            [
                {"type": "vibe_check", "field": "options"},
                {"type": "not_null", "field": "ghost"},
            ]
        ),
        FIELDS,
    )
    assert len(defects["write_q"]) == 2


def test_field_check_still_fires_when_the_action_produces_zero_fields():
    defects = find_expectation_defects(
        config([{"type": "not_null", "field": "anything"}]), {"write_q": set()}
    )
    assert "write_q" in defects
    assert "anything" in defects["write_q"][0]


def test_malformed_field_value_is_reported_not_crashed():
    defects = find_expectation_defects(config([{"type": "not_null", "field": 42}]), FIELDS)
    assert "write_q" in defects
    assert "must be a string or list" in defects["write_q"][0]
    assert "int" in defects["write_q"][0]


def test_named_suite_with_an_unregistered_type_is_reported(tmp_path):
    write_suite(tmp_path, "scenario", [{"type": "vibe_check", "field": "options"}])
    defects = find_expectation_defects(suite_config("scenario"), FIELDS, project_root=tmp_path)
    assert "vibe_check" in defects["write_q"][0]


def test_named_suite_with_a_missing_field_is_reported(tmp_path):
    write_suite(tmp_path, "scenario", [{"type": "not_null", "field": "nonexistent"}])
    defects = find_expectation_defects(suite_config("scenario"), FIELDS, project_root=tmp_path)
    assert "nonexistent" in defects["write_q"][0]


def test_named_suite_that_does_not_exist_is_reported(tmp_path):
    write_suite(tmp_path, "scenario", [{"type": "not_null", "field": "options"}])
    defects = find_expectation_defects(suite_config("missing_suite"), FIELDS, project_root=tmp_path)
    assert "missing_suite" in defects["write_q"][0]


def test_clean_named_suite_reports_no_defects(tmp_path):
    write_suite(
        tmp_path, "scenario", [{"type": "item_count", "field": "options", "params": {"equals": 4}}]
    )
    defects = find_expectation_defects(suite_config("scenario"), FIELDS, project_root=tmp_path)
    assert defects == {}


def test_suite_rules_ride_beside_schema_fields_in_one_file(tmp_path):
    write_schema_file(
        tmp_path,
        "scenario",
        {
            "fields": [{"id": "options", "type": "array", "items": {"type": "string"}}],
            "expectations": [{"type": "item_count", "field": "options", "params": {"equals": 4}}],
        },
    )
    defects = find_expectation_defects(suite_config("scenario"), FIELDS, project_root=tmp_path)
    assert defects == {}


def test_named_suite_is_skipped_without_project_context():
    defects = find_expectation_defects(suite_config("scenario"), FIELDS)
    assert defects == {}


def test_named_suite_without_an_expectations_block_is_reported(tmp_path):
    write_schema_file(tmp_path, "scenario", {"fields": [{"id": "options", "type": "string"}]})
    defects = find_expectation_defects(suite_config("scenario"), FIELDS, project_root=tmp_path)
    assert "no expectations" in defects["write_q"][0]


def test_named_suite_with_invalid_yaml_syntax_is_reported_not_crashed(tmp_path):
    (tmp_path / "agent_actions.yml").write_text(yaml.safe_dump({"schema_path": "schema"}))
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "scenario.yml").write_text(
        "name: scenario\nexpectations:\n  - type: not_null\n    field: [unterminated\n"
    )
    defects = find_expectation_defects(suite_config("scenario"), FIELDS, project_root=tmp_path)
    assert "write_q" in defects
    assert "scenario" in defects["write_q"][0]


def test_defaulted_expect_reads_the_actions_own_schema(tmp_path):
    write_suite(tmp_path, "write_q_schema", [{"type": "not_null", "field": "nonexistent"}])
    defects = find_expectation_defects(
        default_config(schema_name="write_q_schema"), FIELDS, project_root=tmp_path
    )
    assert "nonexistent" in defects["write_q"][0]


def test_defaulted_expect_with_a_clean_schema_suite_reports_no_defects(tmp_path):
    write_suite(tmp_path, "write_q_schema", [{"type": "not_null", "field": "options"}])
    defects = find_expectation_defects(
        default_config(schema_name="write_q_schema"), FIELDS, project_root=tmp_path
    )
    assert defects == {}


def test_defaulted_expect_on_a_schema_without_expectations_block_is_reported(tmp_path):
    write_schema_file(tmp_path, "write_q_schema", {"fields": [{"id": "options", "type": "string"}]})
    defects = find_expectation_defects(
        default_config(schema_name="write_q_schema"), FIELDS, project_root=tmp_path
    )
    assert "no expectations" in defects["write_q"][0]


def test_defaulted_expect_reads_the_inlined_schema_dicts_expectations(tmp_path):
    defects = find_expectation_defects(
        default_config(
            schema={
                "fields": [{"id": "options", "type": "string"}],
                "expectations": [{"type": "not_null", "field": "nonexistent"}],
            }
        ),
        FIELDS,
        project_root=tmp_path,
    )
    assert "nonexistent" in defects["write_q"][0]


def test_defaulted_expect_with_a_clean_inlined_schema_reports_no_defects(tmp_path):
    defects = find_expectation_defects(
        default_config(
            schema={
                "fields": [{"id": "options", "type": "string"}],
                "expectations": [{"type": "not_null", "field": "options"}],
            }
        ),
        FIELDS,
        project_root=tmp_path,
    )
    assert defects == {}


def test_defaulted_expect_on_a_schema_dict_without_expectations_is_reported(tmp_path):
    defects = find_expectation_defects(
        default_config(schema={"fields": [{"id": "options", "type": "string"}]}),
        FIELDS,
        project_root=tmp_path,
    )
    assert "no expectations" in defects["write_q"][0]


def test_an_explicitly_empty_inline_list_is_a_defect():
    defects = find_expectation_defects(config([]), FIELDS)
    assert "empty" in defects["write_q"][0]


def test_defaulted_expect_with_no_schema_at_all_is_reported(tmp_path):
    defects = find_expectation_defects(default_config(), FIELDS, project_root=tmp_path)
    assert "no schema" in defects["write_q"][0]


def test_defaulted_expect_is_skipped_without_project_context():
    defects = find_expectation_defects(default_config(schema_name="write_q_schema"), FIELDS)
    assert defects == {}


def test_llm_judge_negative_votes_is_a_defect():
    action_configs = {
        "write_q": {
            "expect": {
                "expectations": [
                    {
                        "id": "r",
                        "type": "llm_judge",
                        "field": "options",
                        "params": {"rule": "x", "votes": -1},
                    }
                ]
            }
        }
    }
    defects = find_expectation_defects(action_configs, {"write_q": {"options"}})
    assert defects and "votes" in defects["write_q"][0]


def test_llm_judge_non_integer_votes_is_a_defect():
    action_configs = {
        "write_q": {
            "expect": {
                "expectations": [
                    {
                        "id": "r",
                        "type": "llm_judge",
                        "field": "options",
                        "params": {"rule": "x", "votes": "three"},
                    }
                ]
            }
        }
    }
    defects = find_expectation_defects(action_configs, {"write_q": {"options"}})
    assert defects and "votes" in defects["write_q"][0]


def test_llm_judge_positive_votes_is_accepted():
    action_configs = {
        "write_q": {
            "expect": {
                "expectations": [
                    {
                        "id": "r",
                        "type": "llm_judge",
                        "field": "options",
                        "params": {"rule": "x", "votes": 3},
                    }
                ]
            }
        }
    }
    defects = find_expectation_defects(action_configs, {"write_q": {"options"}})
    assert defects == {}


def test_llm_judge_context_ref_to_a_real_field_is_accepted():
    action_configs = {
        "write_q": {
            "expect": {
                "expectations": [
                    {
                        "id": "r",
                        "type": "llm_judge",
                        "field": "options",
                        "params": {
                            "rule": "x",
                            "context": ["extract_quote_context.source_context"],
                        },
                    }
                ]
            }
        }
    }
    available_fields = {"write_q": {"options"}, "extract_quote_context": {"source_context"}}
    assert find_expectation_defects(action_configs, available_fields) == {}


def test_llm_judge_context_ref_to_unknown_action_is_a_defect():
    action_configs = {
        "write_q": {
            "expect": {
                "expectations": [
                    {
                        "id": "r",
                        "type": "llm_judge",
                        "field": "options",
                        "params": {"rule": "x", "context": ["nonexistent.field"]},
                    }
                ]
            }
        }
    }
    defects = find_expectation_defects(action_configs, {"write_q": {"options"}})
    assert defects and "unknown action 'nonexistent'" in defects["write_q"][0]


def test_llm_judge_context_ref_to_unknown_field_is_a_defect():
    action_configs = {
        "write_q": {
            "expect": {
                "expectations": [
                    {
                        "id": "r",
                        "type": "llm_judge",
                        "field": "options",
                        "params": {"rule": "x", "context": ["extract_quote_context.missing_field"]},
                    }
                ]
            }
        }
    }
    available_fields = {"write_q": {"options"}, "extract_quote_context": {"source_context"}}
    defects = find_expectation_defects(action_configs, available_fields)
    assert defects and "does not produce field 'missing_field'" in defects["write_q"][0]


def test_llm_judge_malformed_context_ref_is_a_defect():
    action_configs = {
        "write_q": {
            "expect": {
                "expectations": [
                    {
                        "id": "r",
                        "type": "llm_judge",
                        "field": "options",
                        "params": {"rule": "x", "context": ["no_dot"]},
                    }
                ]
            }
        }
    }
    defects = find_expectation_defects(action_configs, {"write_q": {"options"}})
    assert defects and "must be 'action.field'" in defects["write_q"][0]


def test_llm_judge_non_list_context_value_is_a_defect_not_a_crash():
    action_configs = {
        "write_q": {
            "expect": {
                "expectations": [
                    {
                        "id": "r",
                        "type": "llm_judge",
                        "field": "options",
                        "params": {"rule": "x", "context": 5},
                    }
                ]
            }
        }
    }
    defects = find_expectation_defects(action_configs, {"write_q": {"options"}})
    assert defects and "context must be a list" in defects["write_q"][0]


EXPR_FIELDS = {"write_q": {"score", "verdict", "meta"}}


def _expr_defects(entry, fields=EXPR_FIELDS):
    return find_expectation_defects(config([entry]), fields).get("write_q", [])


def test_valid_expression_entry_has_no_defects():
    assert (
        _expr_defects({"id": "floor", "type": "expression", "params": {"condition": "score >= 80"}})
        == []
    )


def test_expression_with_field_is_a_defect():
    defects = _expr_defects(
        {
            "id": "floor",
            "type": "expression",
            "field": "score",
            "params": {"condition": "score >= 80"},
        }
    )
    assert any("does not take field" in d for d in defects)


def test_expression_udf_condition_defect_names_the_decorator():
    defects = _expr_defects(
        {"id": "floor", "type": "expression", "params": {"condition": "udf:tools.checks.my_check"}}
    )
    assert any("expectation_check" in d for d in defects)


def test_expression_unparseable_condition_is_a_defect():
    defects = _expr_defects(
        {"id": "floor", "type": "expression", "params": {"condition": "score >="}}
    )
    assert any("does not parse" in d for d in defects)


def test_expression_non_string_condition_is_a_defect():
    defects = _expr_defects({"id": "floor", "type": "expression", "params": {"condition": 5}})
    assert any("condition must be a non-empty string" in d for d in defects)


def test_expression_constant_condition_is_a_defect():
    defects = _expr_defects({"id": "floor", "type": "expression", "params": {"condition": '"80"'}})
    assert any("references no record fields" in d for d in defects)


def test_expression_unknown_field_reference_is_a_defect():
    defects = _expr_defects(
        {"id": "floor", "type": "expression", "params": {"condition": "points >= 80"}}
    )
    assert any("does not produce field 'points'" in d for d in defects)


def test_expression_dotted_reference_checks_the_top_segment():
    assert (
        _expr_defects(
            {"id": "m", "type": "expression", "params": {"condition": 'meta.status == "ok"'}}
        )
        == []
    )


def test_expression_missing_condition_reports_once():
    defects = _expr_defects({"id": "floor", "type": "expression"})
    assert len([d for d in defects if "condition" in d]) == 1


def test_missing_field_on_a_deterministic_entry_is_now_a_preflight_defect():
    defects = _expr_defects({"id": "present", "type": "not_null"})
    assert any("requires field" in d for d in defects)


def test_empty_string_field_is_a_defect():
    defects = _expr_defects({"id": "present", "type": "not_null", "field": ""})
    assert any("must not be empty" in d for d in defects)


def test_empty_list_field_is_a_defect():
    defects = _expr_defects({"id": "present", "type": "not_null", "field": []})
    assert any("must not be empty" in d for d in defects)


def test_expression_entry_in_a_suite_file_gets_the_same_checks(tmp_path):
    write_suite(
        tmp_path,
        "scenario",
        [{"id": "floor", "type": "expression", "params": {"condition": "points >= 80"}}],
    )
    defects = find_expectation_defects(suite_config("scenario"), EXPR_FIELDS, project_root=tmp_path)
    assert any("does not produce field 'points'" in d for d in defects["write_q"])


def test_whitespace_only_condition_is_a_defect():
    defects = _expr_defects({"id": "floor", "type": "expression", "params": {"condition": "   "}})
    assert any("condition must be a non-empty string" in d for d in defects)


def test_expression_schema_cross_check_skips_when_the_action_has_no_known_fields():
    defects = find_expectation_defects(
        config([{"id": "floor", "type": "expression", "params": {"condition": "points >= 80"}}]), {}
    ).get("write_q", [])
    assert defects == []
