"""Preflight defect detection for expect blocks."""

from agent_actions.validation.expectations_validator import find_expectation_defects

FIELDS = {"write_q": {"options", "answer", "answer_explanation"}}


def config(expectations, name="write_q"):
    return {name: {"name": name, "expect": {"expectations": expectations}}}


def test_clean_suite_reports_no_defects():
    defects = find_expectation_defects(
        config([{"type": "item_count", "field": "options", "equals": 4}]), FIELDS
    )
    assert defects == {}


def test_unregistered_type_is_reported_with_the_type_name():
    defects = find_expectation_defects(config([{"type": "vibe_check", "field": "options"}]), FIELDS)
    assert "vibe_check" in defects["write_q"][0]


def test_unknown_parameter_is_reported():
    defects = find_expectation_defects(
        config([{"type": "item_count", "field": "options", "equalz": 4}]), FIELDS
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
        config([{"type": "word_count_between", "field": "nonexistent[*]", "max": 5}]), FIELDS
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
