"""The authored shape of one rule: arguments under params:, dbt severity words."""

import pytest
from pydantic import ValidationError

from agent_actions.expectations.types import Expectation


def test_arguments_are_read_from_the_params_block():
    exp = Expectation(id="option_count", type="item_count", field="options", params={"equals": 4})
    assert exp.params == {"equals": 4}


def test_a_rule_with_no_arguments_has_empty_params():
    assert Expectation(type="not_null", field="answer").params == {}


def test_arguments_written_flat_are_refused_and_name_the_params_block():
    with pytest.raises(ValidationError) as excinfo:
        Expectation(id="option_count", type="item_count", field="options", equals=4)
    assert "params" in str(excinfo.value)
    assert "equals" in str(excinfo.value)


def test_a_mistyped_rule_key_is_refused_by_name():
    with pytest.raises(ValidationError) as excinfo:
        Expectation(type="not_null", field="answer", sevrity="warn")
    assert "sevrity" in str(excinfo.value)


def test_severity_defaults_to_error():
    assert Expectation(type="not_null", field="answer").severity == "error"


def test_severity_accepts_warn_and_info():
    assert Expectation(type="not_null", field="answer", severity="warn").severity == "warn"
    assert Expectation(type="not_null", field="answer", severity="info").severity == "info"


def test_severity_fail_is_refused_and_names_its_replacement():
    with pytest.raises(ValidationError) as excinfo:
        Expectation(type="not_null", field="answer", severity="fail")
    assert "error" in str(excinfo.value)


def test_definition_hash_tracks_a_change_inside_params():
    a = Expectation(type="item_count", field="options", params={"equals": 4})
    b = Expectation(type="item_count", field="options", params={"equals": 5})
    assert a.definition_hash() != b.definition_hash()


def test_definition_hash_is_independent_of_argument_order():
    a = Expectation(type="item_count", field="options", params={"equals": 4, "min": 1})
    b = Expectation(type="item_count", field="options", params={"min": 1, "equals": 4})
    assert a.definition_hash() == b.definition_hash()
