"""A scenario's ``break_rules`` turns an honest mock record into one the real check fails.

The mock builds the record that meets every rule, then changes the field a named rule reads
until the registered check fails on it, keeping a value the schema still accepts. A rule it
cannot break, and a pinned value the schema refuses, are each logged once.
"""

from __future__ import annotations

import logging

import pytest

from agent_actions.expectations.runner import run_suite
from agent_actions.expectations.types import Expectation, Suite
from agent_actions.llm.providers.agac.contract import Contract, _conforms, reset_runs
from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator

SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "string"},
        "tone": {"type": "string"},
        "summary": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "score": {"type": "integer", "minimum": 0, "maximum": 10},
    },
    "required": ["code", "tone", "summary", "tags", "score"],
}

RULES = {
    "matches_regex": {
        "type": "matches_regex",
        "field": "code",
        "params": {"pattern": r"^[A-Z]{3}-\d{2}$"},
    },
    "negated": {
        "type": "matches_regex",
        "field": "summary",
        "params": {"pattern": r"\d", "negate": True},
    },
    "accepted_values": {
        "type": "accepted_values",
        "field": "tone",
        "params": {"values": ["calm", "stormy"]},
    },
    "word_count_between": {
        "type": "word_count_between",
        "field": "summary",
        "params": {"min": 3, "max": 8},
    },
    "item_count": {"type": "item_count", "field": "tags", "params": {"min": 1, "max": 3}},
    "not_null": {"type": "not_null", "field": "tone"},
    "element": {"type": "accepted_values", "field": "tags[*]", "params": {"values": ["a", "b"]}},
    "expression": {"type": "expression", "params": {"condition": "score >= 2"}},
}


def _contract(*names: str) -> Contract:
    reset_runs()
    rules = [Expectation(id=name, **RULES[name]) for name in names]
    return Contract(action="extract", rules=rules, context={}, observe=[])


def _honest(contract: Contract) -> dict:
    FakeDataGenerator.set_context(prompt="extract:break")
    record = contract.generate(SCHEMA, 1)
    assert not run_suite(Suite(name="s", expectations=contract.rules), record).failed
    return record


def _failing(contract: Contract, record: dict) -> list[str]:
    return [o.id for o in run_suite(Suite(name="s", expectations=contract.rules), record).failed]


@pytest.mark.parametrize("name", sorted(RULES))
def test_a_named_rule_fails_and_the_schema_still_accepts_the_record(name):
    contract = _contract(name)
    record = _honest(contract)

    broken = contract.break_rules(record, SCHEMA, [contract.rules[0].type], lambda count: 0)

    assert broken == 1
    assert _failing(contract, record) == [name]
    properties = SCHEMA["properties"]
    assert all(_conforms(record[field], schema) for field, schema in properties.items())


def test_all_breaks_the_one_rule_picked():
    contract = _contract("matches_regex", "accepted_values")
    record = _honest(contract)

    assert contract.break_rules(record, SCHEMA, "all", lambda count: 1) == 1

    assert _failing(contract, record) == ["accepted_values"]


def test_a_rule_type_the_action_does_not_check_is_logged_once(caplog):
    contract = _contract("accepted_values")
    record = _honest(contract)

    with caplog.at_level(logging.WARNING):
        assert contract.break_rules(record, SCHEMA, ["item_count"], lambda count: 0) == 0
        assert contract.break_rules(record, SCHEMA, ["item_count"], lambda count: 0) == 0

    warnings = [r.getMessage() for r in caplog.records if "could not break" in r.getMessage()]
    assert len(warnings) == 1 and "item_count" in warnings[0]
    assert _failing(contract, record) == []


def test_a_pinned_value_is_kept_and_one_that_fails_is_logged_once(caplog):
    contract = _contract("accepted_values")
    record = _honest(contract)

    with caplog.at_level(logging.WARNING):
        contract.pin(record, SCHEMA, {"tone": "calm", "score": 99})
        contract.pin(record, SCHEMA, {"score": 99})

    assert record["tone"] == "calm" and record["score"] == 99
    warnings = [r.getMessage() for r in caplog.records if "pins field" in r.getMessage()]
    assert len(warnings) == 1 and "'score'" in warnings[0], warnings
