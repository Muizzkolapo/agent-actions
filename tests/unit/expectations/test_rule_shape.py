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


def test_definition_hash_tracks_a_change_inside_params():
    a = Expectation(type="item_count", field="options", params={"equals": 4})
    b = Expectation(type="item_count", field="options", params={"equals": 5})
    assert a.definition_hash() != b.definition_hash()


def test_definition_hash_is_independent_of_argument_order():
    a = Expectation(type="item_count", field="options", params={"equals": 4, "min": 1})
    b = Expectation(type="item_count", field="options", params={"min": 1, "equals": 4})
    assert a.definition_hash() == b.definition_hash()


def test_severity_fail_is_refused_by_naming_the_replacement_not_the_literal_set():
    with pytest.raises(ValidationError) as excinfo:
        Expectation(type="not_null", field="answer", severity="fail")
    assert "is now 'error'" in str(excinfo.value)


def test_a_mistyped_rule_key_is_not_sent_to_the_params_block():
    with pytest.raises(ValidationError) as excinfo:
        Expectation(type="not_null", field="answer", sevrity="warn")
    message = str(excinfo.value)
    assert "did you mean 'severity'" in message
    assert "params" not in message


def test_a_genuine_argument_is_still_sent_to_the_params_block():
    with pytest.raises(ValidationError) as excinfo:
        Expectation(type="item_count", field="options", equals=4)
    assert "params" in str(excinfo.value)
    assert "did you mean" not in str(excinfo.value)


def test_a_stray_key_and_a_superseded_severity_are_reported_together():
    with pytest.raises(ValidationError) as excinfo:
        Expectation(type="item_count", field="options", equals=4, severity="fail")
    message = str(excinfo.value)
    assert "params" in message
    assert "is now 'error'" in message


@pytest.mark.parametrize(
    "typo,meant",
    [("feild", "field"), ("hnit", "hint"), ("sevrity", "severity"), ("parms", "params")],
)
def test_a_near_miss_on_a_rule_key_names_the_key_it_resembles(typo, meant):
    with pytest.raises(ValidationError) as excinfo:
        Expectation(**{"type": "not_null", "field": "answer", typo: "x"})
    assert f"did you mean '{meant}'" in str(excinfo.value)
