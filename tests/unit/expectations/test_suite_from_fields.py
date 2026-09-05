"""Rules declared on the field they test become suite entries with that selector."""

import pytest
import yaml

from agent_actions.expectations import loader
from agent_actions.expectations.loader import build_suite_from_schema_data, load_named_suite

FIELD_SCOPED_SCHEMA = {
    "name": "fb_page_summary",
    "fields": [
        {
            "id": "summary",
            "type": "string",
            "expectations": [
                {
                    "id": "summary_word_count",
                    "type": "word_count_between",
                    "params": {"min": 10, "max": 80},
                    "severity": "warn",
                }
            ],
        },
        {
            "id": "exam_density",
            "type": "string",
            "expectations": [
                {
                    "id": "exam_density_accepted_values",
                    "type": "accepted_values",
                    "params": {"values": ["high", "medium", "low"]},
                }
            ],
        },
    ],
}


def project(tmp_path, schema_data, name="fb_page_summary"):
    (tmp_path / "agent_actions.yml").write_text(yaml.safe_dump({"schema_path": "schema"}))
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / f"{name}.yml").write_text(yaml.safe_dump(schema_data))
    return tmp_path


def test_a_field_scoped_rule_takes_its_selector_from_the_field():
    suite = build_suite_from_schema_data("fb_page_summary", FIELD_SCOPED_SCHEMA)
    assert [(e.resolved_id, e.field) for e in suite.expectations] == [
        ("summary_word_count", "summary"),
        ("exam_density_accepted_values", "exam_density"),
    ]


def test_field_scoped_rules_keep_their_own_arguments_and_severity():
    suite = build_suite_from_schema_data("fb_page_summary", FIELD_SCOPED_SCHEMA)
    assert suite.expectations[0].params == {"min": 10, "max": 80}
    assert suite.expectations[0].severity == "warn"
    assert suite.expectations[1].severity == "error"


def test_a_file_whose_only_rules_are_field_scoped_is_a_suite():
    suite = build_suite_from_schema_data("fb_page_summary", FIELD_SCOPED_SCHEMA)
    assert len(suite.expectations) == 2


def test_field_scoped_and_top_level_rules_both_load():
    data = dict(FIELD_SCOPED_SCHEMA)
    data["expectations"] = [{"id": "reason_present", "type": "not_null", "field": "density_reason"}]
    suite = build_suite_from_schema_data("fb_page_summary", data)
    assert [e.resolved_id for e in suite.expectations] == [
        "summary_word_count",
        "exam_density_accepted_values",
        "reason_present",
    ]


def test_a_field_scoped_rule_may_not_declare_its_own_selector():
    data = {
        "fields": [
            {
                "id": "summary",
                "type": "string",
                "expectations": [{"type": "not_null", "field": "exam_density"}],
            }
        ]
    }
    with pytest.raises(ValueError, match="summary") as excinfo:
        build_suite_from_schema_data("page_shape", data)
    assert "field:" in str(excinfo.value)


def test_a_field_identified_by_name_still_stamps_its_selector():
    data = {
        "fields": [{"name": "summary", "type": "string", "expectations": [{"type": "not_null"}]}]
    }
    suite = build_suite_from_schema_data("fb_page_summary", data)
    assert suite.expectations[0].field == "summary"


def test_a_schema_with_no_rules_anywhere_is_still_not_a_suite():
    with pytest.raises(ValueError, match="no expectations"):
        build_suite_from_schema_data("shape_only", {"fields": [{"id": "summary"}]})


def test_load_named_suite_reads_field_scoped_rules_through_the_schema_route(tmp_path):
    root = project(tmp_path, FIELD_SCOPED_SCHEMA)
    suite = load_named_suite("fb_page_summary", root)
    assert [e.field for e in suite.expectations] == ["summary", "exam_density"]


def test_a_field_scoped_rule_that_declares_a_selector_fails_the_named_route(tmp_path):
    data = {
        "fields": [
            {
                "id": "summary",
                "type": "string",
                "expectations": [{"type": "not_null", "field": "elsewhere"}],
            }
        ]
    }
    root = project(tmp_path, data, name="bad_suite")
    with pytest.raises(loader.SuiteLoadError, match="summary"):
        load_named_suite("bad_suite", root)


def test_rules_nested_below_a_top_level_field_are_refused_not_dropped():
    data = {
        "fields": [
            {"id": "summary", "type": "string", "expectations": [{"type": "not_null"}]},
            {
                "id": "scores",
                "type": "object",
                "properties": {
                    "accuracy": {"type": "number", "expectations": [{"type": "not_null"}]}
                },
            },
        ]
    }
    with pytest.raises(ValueError, match="accuracy"):
        build_suite_from_schema_data("page_shape", data)


def test_a_non_list_fields_value_is_a_named_error_not_a_crash():
    with pytest.raises(ValueError, match="fields"):
        build_suite_from_schema_data("bad_shape", {"fields": 3, "expectations": []})


def test_nested_rules_are_refused_even_when_the_field_has_rules_of_its_own():
    data = {
        "fields": [
            {
                "id": "options",
                "type": "array",
                "expectations": [{"type": "item_count", "params": {"min": 2}}],
                "items": {
                    "type": "object",
                    "properties": {"text": {"expectations": [{"type": "not_null"}]}},
                },
            }
        ]
    }
    with pytest.raises(ValueError, match="text"):
        build_suite_from_schema_data("page_shape", data)


def test_a_nested_property_merely_named_expectations_is_not_mistaken_for_rules():
    data = {
        "fields": [
            {
                "id": "survey",
                "type": "object",
                "expectations": [{"type": "not_null"}],
                "properties": {"expectations": {"type": "string"}},
            }
        ]
    }
    suite = build_suite_from_schema_data("page_shape", data)
    assert [e.field for e in suite.expectations] == ["survey"]


def test_a_scalar_where_rules_belong_is_a_named_error_not_a_crash():
    with pytest.raises(ValueError, match="expectations"):
        build_suite_from_schema_data("page_shape", {"expectations": 5})
    with pytest.raises(ValueError, match="expectations"):
        build_suite_from_schema_data("page_shape", {"fields": [{"id": "a", "expectations": 5}]})


def test_unreachable_rules_are_refused_in_a_file_with_no_top_level_fields():
    data = {
        "name": "candidate_facts",
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"fact": {"type": "string", "expectations": [{"type": "not_null"}]}},
        },
        "expectations": [{"id": "has_quote", "type": "not_null", "field": "quote"}],
    }
    with pytest.raises(ValueError, match="fact"):
        build_suite_from_schema_data("candidate_facts", data)


def test_rules_on_a_dict_inside_a_list_are_refused_not_dropped():
    data = {
        "fields": [
            {"id": "a", "expectations": [{"id": "a_ok", "type": "not_null"}]},
            {
                "id": "b",
                "type": "array",
                "items": {
                    "type": "object",
                    "fields": [
                        {"id": "inner", "expectations": [{"id": "inner_ok", "type": "not_null"}]}
                    ],
                },
            },
        ]
    }
    with pytest.raises(ValueError, match="inner"):
        build_suite_from_schema_data("page_shape", data)


def test_a_nested_list_that_is_not_rules_is_not_mistaken_for_them():
    data = {
        "fields": [
            {
                "id": "survey",
                "type": "object",
                "expectations": [{"type": "not_null"}],
                "properties": {"stats": {"expectations": ["free text", "not a rule"]}},
            }
        ]
    }
    suite = build_suite_from_schema_data("page_shape", data)
    assert [e.field for e in suite.expectations] == ["survey"]


def test_a_record_scoped_rule_under_a_field_is_refused_where_the_author_wrote_it():
    data = {
        "fields": [
            {
                "id": "score",
                "type": "integer",
                "expectations": [{"type": "expression", "params": {"condition": "score >= 0"}}],
            }
        ]
    }
    with pytest.raises(ValueError) as excinfo:
        build_suite_from_schema_data("page_shape", data)
    message = str(excinfo.value)
    assert "expression" in message
    assert "expectations: block" in message
