"""The mock answers with records that pass the action's own expectation rules.

Each built-in rule and each schema keyword gets records from several seeds, online and in
a batch, and the real runner must pass every one. An output field named like an observed
input field copies that input. Constraints that contradict are logged once per action and
field, and a record still comes back.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from agent_actions.expectations import registry
from agent_actions.expectations.loader import build_inline_suite
from agent_actions.expectations.runner import run_suite
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient, MockBatchState
from agent_actions.llm.providers.agac.client import AgacClient
from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator
from agent_actions.utils.jsonschema_cache import checked_validator

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "invoice_id": {"type": "string"},
        "currency": {"type": "string"},
        "summary": {"type": "string"},
        "title": {"type": "string"},
        "total": {"type": "number", "minimum": 0, "maximum": 1000},
        "tags": {"type": "array", "items": {"type": "string"}},
        "note": {"type": ["null", "string"]},
    },
    "additionalProperties": False,
}

RULES: dict[str, dict[str, Any]] = {
    "not_null": {"type": "not_null", "field": "summary"},
    "no_null_fields": {"type": "no_null_fields"},
    "item_count": {"type": "item_count", "field": "tags", "params": {"min": 4, "max": 6}},
    "item_count_equals": {"type": "item_count", "field": "tags", "params": {"equals": 5}},
    "word_count_between": {
        "type": "word_count_between",
        "field": "summary",
        "params": {"min": 12, "max": 15},
    },
    "accepted_values": {
        "type": "accepted_values",
        "field": "currency",
        "params": {"values": ["EUR", "USD"]},
    },
    "matches_regex": {
        "type": "matches_regex",
        "field": "invoice_id",
        "params": {"pattern": r"^INV-\d{4}$"},
    },
    "matches_regex_negate": {
        "type": "matches_regex",
        "field": "invoice_id",
        "params": {"pattern": r"\d", "negate": True},
    },
    "element_regex": {
        "type": "matches_regex",
        "field": "tags[*]",
        "params": {"pattern": r"^[a-z]{3}$"},
    },
    "expression": {"type": "expression", "params": {"condition": "total > 500"}},
}

SEEDS = [f"Extract invoice {i}." for i in range(6)]


@pytest.fixture(autouse=True)
def _fresh_mock():
    AgacClient.reset()
    yield
    AgacClient.reset()
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()


def _config(rules: list[dict], observe: list[str] | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {"name": "extract", "json_mode": True}
    if rules:
        config["expect"] = {"repair": "auto", "expectations": rules}
    if observe:
        config["context_scope"] = {"observe": observe}
    return config


def _online(schema, rules, prompt, context=None, observe=None, config=None) -> dict[str, Any]:
    [record] = AgacClient.call_json(
        None,
        config or _config(rules, observe),
        prompt,
        json.dumps(context or {"source": {"page_content": "..."}}),
        {"name": "out", "schema": schema},
    )
    return record


def _batch(schema, rules, prompt, context=None, observe=None, config=None) -> dict[str, Any]:
    client = AgacBatchClient()
    config = {
        **(config or _config(rules, observe)),
        "model_name": "agac-model",
        "compiled_schema": schema,
    }
    row = {
        "target_id": "r1",
        "content": context or {"source": {"page_content": "..."}},
        "prompt": prompt,
    }
    tasks = client.prepare_tasks([row], config)
    AgacBatchClient._batches["b"] = MockBatchState(batch_id="b", status="completed")
    AgacBatchClient._tasks_by_batch["b"] = tasks
    line = client._fetch_raw_results("b").decode("utf-8").strip()
    body = json.loads(line)["response"]["body"]
    return json.loads(body["choices"][0]["message"]["content"])


ANSWER = {"online": _online, "batch": _batch}


def _failures(rules: list[dict], record: dict[str, Any]) -> list[str]:
    result = run_suite(build_inline_suite(rules, "extract"), record)
    return [f"{o.id}: {o.detail}" for o in result.outcomes if not o.passed]


@pytest.mark.parametrize("mode", sorted(ANSWER))
@pytest.mark.parametrize("rule", sorted(RULES))
def test_each_rule_passes_the_real_runner(mode, rule):
    rules = [RULES[rule]]
    for prompt in SEEDS:
        record = ANSWER[mode](SCHEMA, rules, prompt)

        assert _failures(rules, record) == [], (prompt, record)
        assert checked_validator(SCHEMA).is_valid(record), record


@pytest.mark.parametrize("mode", sorted(ANSWER))
def test_every_rule_at_once_passes_the_real_runner(mode):
    # One rule per field: the negated pattern and the shape rule both name invoice_id.
    rules = [
        RULES[name]
        for name in sorted(RULES)
        if name not in ("item_count_equals", "element_regex", "matches_regex_negate")
    ]
    for prompt in SEEDS:
        record = ANSWER[mode](SCHEMA, rules, prompt)

        assert _failures(rules, record) == [], (prompt, record)


@pytest.mark.parametrize("mode", sorted(ANSWER))
def test_a_project_defined_check_is_met(mode, monkeypatch):
    def even_length(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
        return len(str(value)) % 2 == 0, f"{value!r} has odd length"

    monkeypatch.setitem(
        registry._REGISTRY,
        "mock_even_length",
        registry.ExpectationType("mock_even_length", frozenset(), frozenset(), even_length),
    )
    rules = [{"type": "mock_even_length", "field": "summary"}]
    for prompt in SEEDS:
        record = ANSWER[mode](SCHEMA, rules, prompt)

        assert _failures(rules, record) == [], record


def test_online_and_batch_answer_one_request_alike():
    rules = [RULES["matches_regex"], RULES["accepted_values"]]
    online = _online(SCHEMA, rules, SEEDS[0])
    batch = _batch(SCHEMA, rules, SEEDS[0])

    assert _failures(rules, online) == _failures(rules, batch) == []


def test_a_judged_rule_is_left_to_the_judge():
    rules = [{"type": "llm_judge", "field": "summary", "params": {"rule": "Is it short?"}}]

    record = _online(SCHEMA, rules, SEEDS[0])

    assert set(record) == set(SCHEMA["properties"])


class TestSchemaKeywords:
    CASES = {
        "pattern": {"type": "string", "pattern": r"^[A-Z]{2}\d{3}$"},
        "pattern_in_bounds": {"type": "string", "pattern": r"^x{2,9}$", "minLength": 5},
        "enum": {"type": "string", "enum": ["low", "high"]},
        "bounds": {"type": "integer", "minimum": 3, "maximum": 7},
        "length": {"type": "string", "minLength": 40, "maxLength": 60},
        "items": {"type": "array", "items": {"type": "string"}, "minItems": 4, "maxItems": 5},
        "items_pattern": {
            "type": "array",
            "items": {"type": "string", "pattern": r"^#[0-9a-f]{6}$"},
        },
    }

    @pytest.mark.parametrize("case", sorted(CASES))
    def test_a_generated_value_conforms(self, case):
        schema = self.CASES[case]
        for seed in range(30):
            for attempt in (1, 2, 3):
                FakeDataGenerator.set_context(seed=seed)
                value = FakeDataGenerator.generate_from_schema(schema, attempt, field_name="code")

                assert checked_validator(schema).is_valid(value), (seed, attempt, value)

    @pytest.mark.parametrize("mode", sorted(ANSWER))
    def test_a_pattern_on_a_unified_field_conforms(self, mode):
        schema = {"name": "out", "fields": [{"id": "code", "type": "string", "pattern": r"^Z\d+$"}]}
        record = ANSWER[mode](schema, [], SEEDS[0])

        assert record["code"].startswith("Z") and record["code"][1:].isdigit()


class TestUpstreamEcho:
    CONTEXT = {"extract": {"invoice_id": "INV-0042", "total": "not a number"}}

    @pytest.mark.parametrize("mode", sorted(ANSWER))
    def test_an_observed_field_of_the_same_name_is_copied(self, mode):
        record = ANSWER[mode](
            SCHEMA, [], SEEDS[0], context=self.CONTEXT, observe=["extract.invoice_id"]
        )

        assert record["invoice_id"] == "INV-0042"

    def test_a_wildcard_observe_copies_nothing(self):
        """A loop's writer observes `prior.*`, which holds the field it rewrites."""
        record = _online(SCHEMA, [], SEEDS[0], context=self.CONTEXT, observe=["extract.*"])

        assert record["invoice_id"] != "INV-0042"

    def test_an_input_that_breaks_the_schema_is_not_copied(self):
        record = _online(SCHEMA, [], SEEDS[0], context=self.CONTEXT, observe=["extract.total"])

        assert isinstance(record["total"], float)

    def test_an_input_that_breaks_a_rule_is_not_copied(self):
        rules = [{"type": "matches_regex", "field": "invoice_id", "params": {"pattern": "^X-"}}]

        record = _online(
            SCHEMA, rules, SEEDS[0], context=self.CONTEXT, observe=["extract.invoice_id"]
        )

        assert record["invoice_id"].startswith("X-")

    @pytest.mark.parametrize("mode", sorted(ANSWER))
    def test_a_loop_writer_does_not_copy_the_previous_iteration(self, mode):
        """A copy of the field the loop rewrites would hold every round on one value."""
        from agent_actions.config.includes import expand_workflow_includes
        from agent_actions.config.loops import expand_loops

        branch = {
            "branch": "rewrite_round",
            "description": "Rewrite, then check",
            "inputs": {"prior": "the previous check"},
            "outputs": ["check"],
            "actions": [
                {
                    "name": "write",
                    "intent": "Write",
                    "prompt": "$wf.Write",
                    "schema": "draft",
                    "context_scope": {"observe": ["prior.invoice_id"]},
                },
                {
                    "name": "check",
                    "kind": "tool",
                    "impl": "check_it",
                    "intent": "Check",
                    "schema": "verdict",
                    "dependencies": ["write"],
                },
            ],
        }
        workflow = {
            "name": "wf",
            "actions": [
                {
                    "loop": "round",
                    "include": "rewrite_round",
                    "max_iterations": 2,
                    "feedback": {"prior": "check"},
                    "until": "check.passed == true",
                    "result": "check",
                }
            ],
        }
        data, _ = expand_workflow_includes(workflow, "wf.yml", {"rewrite_round": branch}, [])
        writer = next(a for a in expand_loops(data)["actions"] if a["name"] == "round_iter2__write")
        [observed] = writer["context_scope"]["observe"]
        context = {observed.split(".")[0]: {"invoice_id": "INV-1"}}

        record = ANSWER[mode](
            SCHEMA, [], SEEDS[0], context=context, config={**writer, "json_mode": True}
        )

        assert observed.endswith(".invoice_id")
        assert record["invoice_id"] != "INV-1"

    def test_an_unobserved_field_is_not_copied(self):
        record = _online(SCHEMA, [], SEEDS[0], context=self.CONTEXT, observe=["extract.total"])

        assert record["invoice_id"] != "INV-0042"


class TestUnsatisfiable:
    CONTRADICTION = [
        {"type": "accepted_values", "field": "level", "params": {"values": ["urgent"]}},
    ]
    SCHEMA = {
        "type": "object",
        "properties": {"level": {"type": "string", "enum": ["low", "high"]}},
    }

    def _warnings(self, caplog) -> list[str]:
        return [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING and "could not meet" in r.getMessage()
        ]

    @pytest.mark.parametrize("mode", sorted(ANSWER))
    def test_it_is_logged_once_and_a_record_still_comes_back(self, mode, caplog):
        caplog.set_level(logging.WARNING)
        records = [ANSWER[mode](self.SCHEMA, self.CONTRADICTION, prompt) for prompt in SEEDS]

        assert all(r["level"] in ("low", "high") for r in records)
        [warning] = self._warnings(caplog)
        assert "'extract'" in warning and "'level'" in warning
        assert "enum=['low', 'high']" in warning and "accepted_values" in warning

    def test_a_word_count_no_length_allows_is_named(self, caplog):
        caplog.set_level(logging.WARNING)
        schema = {"type": "object", "properties": {"code": {"type": "string", "maxLength": 5}}}
        rules = [{"type": "word_count_between", "field": "code", "params": {"min": 10}}]

        record = _online(schema, rules, SEEDS[0])

        assert isinstance(record["code"], str)
        [warning] = self._warnings(caplog)
        assert "maxLength=5" in warning and "word_count_between" in warning

    def test_a_reset_logs_it_again(self, caplog):
        caplog.set_level(logging.WARNING)
        _online(self.SCHEMA, self.CONTRADICTION, SEEDS[0])
        AgacClient.reset()
        _online(self.SCHEMA, self.CONTRADICTION, SEEDS[1])

        assert len(self._warnings(caplog)) == 2


class TestAPatternOnAFieldThatIsNotAString:
    """The real check matches against `str(value)`, so a number can meet a pattern."""

    SCHEMA = {
        "type": "object",
        "properties": {"year": {"type": "integer", "minimum": 1900, "maximum": 2100}},
        "additionalProperties": False,
    }
    RULES = [{"type": "matches_regex", "field": "year", "params": {"pattern": r"^(19|20)\d{2}$"}}]

    @pytest.mark.parametrize("mode", sorted(ANSWER))
    def test_the_value_keeps_its_schema_type_and_meets_the_pattern(self, mode, caplog):
        caplog.set_level(logging.WARNING)
        for prompt in SEEDS:
            record = ANSWER[mode](self.SCHEMA, self.RULES, prompt)

            assert checked_validator(self.SCHEMA).is_valid(record), record
            assert _failures(self.RULES, record) == [], record
        assert not [r for r in caplog.records if "could not meet" in r.getMessage()]


def test_a_record_the_schema_refuses_ranks_below_one_that_fails_rules(monkeypatch):
    """Of two failing attempts, the one that keeps the schema is returned."""
    from agent_actions.llm.providers.agac.contract import Contract

    schema = {
        "type": "object",
        "properties": {"code": {"type": "string", "maxLength": 3}},
        "additionalProperties": False,
    }
    rules = [
        {"type": "accepted_values", "field": "code", "params": {"values": ["TOOLONG"]}},
        {"type": "matches_regex", "field": "code", "params": {"pattern": "^T"}},
    ]
    values = iter(["TOOLONG"])
    monkeypatch.setattr(Contract, "_value", lambda *_args: next(values, "abc"))
    contract = Contract.for_request(_config(rules), "extract", "{}")

    record = contract.generate(schema, 1)

    assert record == {"code": "abc"}


def test_a_field_value_the_schema_refuses_ranks_below_one_that_fails_rules(monkeypatch):
    from agent_actions.llm.providers.agac.contract import Contract, _FieldPlan

    schema = {"type": "string", "maxLength": 3}
    rules = [{"type": "accepted_values", "field": "code", "params": {"values": ["TOOLONG"]}}]
    values = iter(["abc", "TOOLONG"] * 20)
    monkeypatch.setattr(Contract, "_candidate", lambda *_args: next(values))
    contract = Contract.for_request(_config(rules), "extract", "{}")

    value = contract._value("code", schema, _FieldPlan(rules=contract.rules), 1, {})

    assert value == "abc"
