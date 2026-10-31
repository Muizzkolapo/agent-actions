"""Preflight defect detection for expect blocks."""

import pytest
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


@pytest.mark.parametrize(
    ("entry", "fragment"),
    [
        pytest.param(
            {"type": "vibe_check", "field": "options"}, "vibe_check", id="unregistered-type"
        ),
        pytest.param(
            {"type": "item_count", "field": "options", "params": {"equalz": 4}},
            "equalz",
            id="unknown-parameter",
        ),
        pytest.param(
            {"type": "word_count_ratio", "field": "options"}, "max_ratio", id="missing-parameter"
        ),
        pytest.param(
            {"type": "not_null", "field": "nonexistent"}, "nonexistent", id="absent-field"
        ),
        # a wildcard selector is checked against its base name
        pytest.param(
            {"type": "word_count_between", "field": "nonexistent[*]", "params": {"max": 5}},
            "nonexistent",
            id="absent-wildcard-field",
        ),
        pytest.param(
            {
                "type": "not_null",
                "field": "options",
                "params": {"row_condition": "not a condition"},
            },
            "row_condition",
            id="unparseable-row-condition",
        ),
        pytest.param(
            {"type": "not_null", "field": "options", "params": {"row_condition": "ghost == 'x'"}},
            "ghost",
            id="row-condition-absent-field",
        ),
    ],
)
def test_inline_entry_defect_is_reported(entry, fragment):
    defects = find_expectation_defects(config([entry]), FIELDS)
    assert fragment in defects["write_q"][0]


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


@pytest.mark.parametrize(
    ("written", "suite_name", "fragment"),
    [
        pytest.param(
            [{"type": "vibe_check", "field": "options"}],
            "scenario",
            "vibe_check",
            id="unregistered-type",
        ),
        pytest.param(
            [{"type": "not_null", "field": "nonexistent"}],
            "scenario",
            "nonexistent",
            id="absent-field",
        ),
        pytest.param(
            [{"type": "not_null", "field": "options"}],
            "missing_suite",
            "missing_suite",
            id="suite-does-not-exist",
        ),
    ],
)
def test_named_suite_defect_is_reported(tmp_path, written, suite_name, fragment):
    write_suite(tmp_path, "scenario", written)
    defects = find_expectation_defects(suite_config(suite_name), FIELDS, project_root=tmp_path)
    assert fragment in defects["write_q"][0]


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


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        pytest.param({"rule": "x", "votes": -1}, "votes", id="negative-votes"),
        pytest.param({"rule": "x", "votes": "three"}, "votes", id="non-int-votes"),
        pytest.param(
            {"rule": "x", "context": ["nonexistent.field"]},
            "unknown action 'nonexistent'",
            id="context-unknown-action",
        ),
        pytest.param(
            {"rule": "x", "context": ["no_dot"]},
            "must be 'action.field'",
            id="context-malformed-ref",
        ),
        # a defect, not a crash
        pytest.param({"rule": "x", "context": 5}, "context must be a list", id="context-non-list"),
    ],
)
def test_llm_judge_bad_params_is_a_defect(params, fragment):
    action_configs = {
        "write_q": {
            "expect": {
                "expectations": [
                    {"id": "r", "type": "llm_judge", "field": "options", "params": params}
                ]
            }
        }
    }
    defects = find_expectation_defects(action_configs, {"write_q": {"options"}})
    assert defects and fragment in defects["write_q"][0]


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


EXPR_FIELDS = {"write_q": {"score", "verdict", "meta"}}


def _expr_defects(entry, fields=EXPR_FIELDS):
    return find_expectation_defects(config([entry]), fields).get("write_q", [])


def test_valid_expression_entry_has_no_defects():
    assert (
        _expr_defects({"id": "floor", "type": "expression", "params": {"condition": "score >= 80"}})
        == []
    )


@pytest.mark.parametrize(
    ("entry", "fragment"),
    [
        pytest.param(
            {
                "id": "floor",
                "type": "expression",
                "field": "score",
                "params": {"condition": "score >= 80"},
            },
            "does not take field",
            id="expression-with-field",
        ),
        # the defect names the decorator
        pytest.param(
            {
                "id": "floor",
                "type": "expression",
                "params": {"condition": "udf:tools.checks.my_check"},
            },
            "expectation_check",
            id="udf-condition",
        ),
        pytest.param(
            {"id": "floor", "type": "expression", "params": {"condition": "score >="}},
            "does not parse",
            id="unparseable-condition",
        ),
        pytest.param(
            {"id": "floor", "type": "expression", "params": {"condition": 5}},
            "condition must be a non-empty string",
            id="non-string-condition",
        ),
        pytest.param(
            {"id": "floor", "type": "expression", "params": {"condition": "   "}},
            "condition must be a non-empty string",
            id="whitespace-condition",
        ),
        pytest.param(
            {"id": "floor", "type": "expression", "params": {"condition": '"80"'}},
            "references no record fields",
            id="constant-condition",
        ),
        pytest.param(
            {"id": "floor", "type": "expression", "params": {"condition": "points >= 80"}},
            "does not produce field 'points'",
            id="unknown-field-reference",
        ),
        pytest.param(
            {"id": "present", "type": "not_null"},
            "requires field",
            id="deterministic-entry-no-field",
        ),
        pytest.param(
            {"id": "present", "type": "not_null", "field": ""},
            "must not be empty",
            id="empty-string-field",
        ),
        pytest.param(
            {"id": "present", "type": "not_null", "field": []},
            "must not be empty",
            id="empty-list-field",
        ),
    ],
)
def test_entry_defect_is_reported(entry, fragment):
    assert any(fragment in d for d in _expr_defects(entry))


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


def test_expression_entry_in_a_suite_file_gets_the_same_checks(tmp_path):
    write_suite(
        tmp_path,
        "scenario",
        [{"id": "floor", "type": "expression", "params": {"condition": "points >= 80"}}],
    )
    defects = find_expectation_defects(suite_config("scenario"), EXPR_FIELDS, project_root=tmp_path)
    assert any("does not produce field 'points'" in d for d in defects["write_q"])


def test_expression_schema_cross_check_skips_when_the_action_has_no_known_fields():
    defects = find_expectation_defects(
        config([{"id": "floor", "type": "expression", "params": {"condition": "points >= 80"}}]), {}
    ).get("write_q", [])
    assert defects == []


def test_a_row_condition_over_a_produced_field_is_accepted():
    defects = find_expectation_defects(
        config(
            [
                {
                    "type": "not_null",
                    "field": "options",
                    "params": {"row_condition": "answer == 'x'"},
                }
            ]
        ),
        FIELDS,
    )
    assert defects == {}


NOT_NULL = [{"type": "not_null", "field": "options"}]


def action_config(name="a", *, expect, **action_keys):
    return {name: {"name": name, "expect": expect, **action_keys}}


def test_a_valid_repair_prompt_mapping_is_accepted():
    defects = find_expectation_defects(
        action_config(
            expect={"repair": {"prompt": "redo: {failed_lines}"}, "expectations": NOT_NULL}
        ),
        {"a": {"options"}},
    )
    assert "a" not in defects


def test_a_repair_prompt_naming_an_unknown_placeholder_is_a_defect():
    defects = find_expectation_defects(
        action_config(expect={"repair": {"prompt": "redo: {nope}"}, "expectations": NOT_NULL}),
        {"a": {"options"}},
    )
    assert any("nope" in m for m in defects["a"])


def test_observe_on_a_batch_action_is_allowed():
    # The batch path validates and attaches the verdict, so the same expect:
    # block works in either run_mode.
    defects = find_expectation_defects(
        action_config(run_mode="batch", expect={"repair": "none", "expectations": NOT_NULL}),
        {"a": {"options"}},
    )
    assert defects == {}


def test_repair_on_a_batch_action_is_allowed():
    # Batch runs the repair loop as a resubmission round, so the same expect:
    # block works in either run_mode.
    defects = find_expectation_defects(
        action_config(run_mode="batch", expect={"repair": "auto", "expectations": NOT_NULL}),
        {"a": {"options"}},
    )
    assert defects == {}


def test_repair_on_a_file_granularity_action_is_a_defect():
    defects = find_expectation_defects(
        action_config(granularity="file", expect={"repair": "retry", "expectations": NOT_NULL}),
        {"a": {"options"}},
    )
    assert any("granularity" in m for m in defects["a"])


def test_repair_file_granularity_defect_fires_for_the_enum_value():
    from agent_actions.config.types import Granularity

    defects = find_expectation_defects(
        action_config(
            granularity=Granularity.FILE, expect={"repair": "auto", "expectations": NOT_NULL}
        ),
        {"a": {"options"}},
    )
    assert any("granularity" in m for m in defects["a"])


def test_observe_on_a_file_granularity_action_is_allowed():
    defects = find_expectation_defects(
        action_config(granularity="file", expect={"repair": "none", "expectations": NOT_NULL}),
        {"a": {"options"}},
    )
    assert defects == {}


def test_repair_with_a_non_mapping_schema_is_a_defect():
    defects = find_expectation_defects(
        action_config(
            schema="schema/wf/a.yml", expect={"repair": "auto", "expectations": NOT_NULL}
        ),
        {"a": {"options"}},
    )
    assert any("schema" in m for m in defects["a"])


def test_record_granularity_repair_reports_no_defects():
    defects = find_expectation_defects(
        action_config(
            granularity="Record",
            run_mode="online",
            schema={"type": "object"},
            expect={"repair": "retry", "expectations": NOT_NULL},
        ),
        {"a": {"options"}},
    )
    assert defects == {}


def test_repair_on_a_tool_action_is_a_defect():
    defects = find_expectation_defects(
        action_config(kind="tool", expect={"repair": "retry", "expectations": NOT_NULL}),
        {"a": {"options"}},
    )
    assert any("tool" in m for m in defects["a"])


def test_repair_on_a_tool_vendor_action_is_a_defect():
    defects = find_expectation_defects(
        action_config(model_vendor="tool", expect={"repair": "auto", "expectations": NOT_NULL}),
        {"a": {"options"}},
    )
    assert any("tool" in m for m in defects["a"])


def test_observe_on_a_tool_action_is_allowed():
    defects = find_expectation_defects(
        action_config(kind="tool", expect={"repair": "none", "expectations": NOT_NULL}),
        {"a": {"options"}},
    )
    assert defects == {}


def test_repair_with_an_unresolved_schema_name_is_a_defect():
    # A declared schema that failed to inline leaves schema absent and
    # schema_name set; the structural gate would silently check shape only.
    defects = find_expectation_defects(
        action_config(schema_name="a_schema", expect={"repair": "auto", "expectations": NOT_NULL}),
        {"a": {"options"}},
    )
    assert any("schema" in m for m in defects["a"])


def test_repair_with_an_inlined_schema_and_residual_name_is_allowed():
    defects = find_expectation_defects(
        action_config(
            schema={"type": "object"},
            schema_name="a_schema",
            expect={"repair": "auto", "expectations": NOT_NULL},
        ),
        {"a": {"options"}},
    )
    assert defects == {}


JUDGE_WITH_CONTEXT = [
    {
        "id": "grounded",
        "type": "llm_judge",
        "field": "options",
        "params": {"rule": "grounded in the source", "context": ["research.findings"]},
    }
]


def test_a_judged_context_ref_on_a_batch_action_is_a_defect():
    # Batch has no llm_context to resolve the ref against, so every record
    # would fail on "no context source was provided" and a downstream guard
    # would drop the whole action's output.
    defects = find_expectation_defects(
        action_config(
            run_mode="batch", expect={"repair": "none", "expectations": JUDGE_WITH_CONTEXT}
        ),
        {"a": {"options"}, "research": {"findings"}},
    )
    assert any("context" in m and "batch" in m for m in defects["a"])


def test_a_judged_rule_without_context_is_allowed_in_batch():
    judged = [{"id": "ok", "type": "llm_judge", "field": "options", "params": {"rule": "is good"}}]
    defects = find_expectation_defects(
        action_config(run_mode="batch", expect={"repair": "none", "expectations": judged}),
        {"a": {"options"}},
    )
    assert defects == {}


def test_a_judged_context_ref_is_allowed_online():
    defects = find_expectation_defects(
        action_config(
            run_mode="online", expect={"repair": "none", "expectations": JUDGE_WITH_CONTEXT}
        ),
        {"a": {"options"}, "research": {"findings"}},
    )
    assert defects == {}
