"""`agac usage` sums the usage entries a workflow's runs stored, per action and kind.

An entry is one run's online calls of one action, or one batch. The report adds them up
per action, kind, pricing and model, in the order the actions run, with a total. With a
price table each row gets an estimated cost; a row the table cannot price has none.
"""

from __future__ import annotations

import pytest

from agent_actions.cli.usage import usage_report
from agent_actions.llm.config.prices import parse_prices

PRICES = parse_prices({"m": {"input": 1.0, "output": 5.0, "batch_discount": 0.5}})


def _row(kind: str, calls: int, *, batch: bool = False, model: str = "m") -> dict:
    return {
        "kind": kind,
        "batch": batch,
        "model": model,
        "calls": calls,
        "input_tokens": 1_000_000 * calls,
        "output_tokens": 100_000 * calls,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


def _summed(calls: int, cost: float | None) -> dict:
    return {
        "calls": calls,
        "input_tokens": 1_000_000 * calls,
        "output_tokens": 100_000 * calls,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "estimated_cost": cost,
    }


ENTRIES = [
    {"action": "write", "run_id": "run-1", "rows": [_row("main", 2), _row("judge", 10)]},
    {"action": "write", "run_id": "run-2", "rows": [_row("main", 1), _row("repair", 1)]},
    {
        "action": "extract",
        "run_id": "run-2",
        "batch_id": "b1",
        "rows": [_row("main", 4, batch=True)],
    },
    {
        "action": "extract",
        "run_id": "run-3",
        "batch_id": "b2",
        "rows": [_row("judge", 8, batch=True)],
    },
]


def test_the_json_report_has_this_shape():
    report = usage_report(ENTRIES, {}, ["extract", "write"])

    assert report == {
        "runs": ["run-1", "run-2", "run-3"],
        "actions": {
            "extract": {
                **_summed(12, None),
                "by_kind": [
                    {**_row("main", 4, batch=True), "estimated_cost": None},
                    {**_row("judge", 8, batch=True), "estimated_cost": None},
                ],
            },
            "write": {
                **_summed(14, None),
                "by_kind": [
                    {**_row("main", 3), "estimated_cost": None},
                    {**_row("repair", 1), "estimated_cost": None},
                    {**_row("judge", 10), "estimated_cost": None},
                ],
            },
        },
        "total": _summed(26, None),
        "priced": False,
        "unpriced": ["prices.m"],
    }


def test_a_batch_action_s_runs_add_up_and_its_judge_batch_is_judge_and_batch_priced():
    extract = usage_report(ENTRIES, {}, [])["actions"]["extract"]

    assert extract["calls"] == 4 + 8
    assert [(row["kind"], row["batch"], row["calls"]) for row in extract["by_kind"]] == [
        ("main", True, 4),
        ("judge", True, 8),
    ]


def test_with_a_price_table_each_row_and_each_sum_has_an_estimated_cost():
    report = usage_report(ENTRIES, PRICES, ["extract", "write"])

    costs = {
        (name, row["kind"]): row["estimated_cost"]
        for name, action in report["actions"].items()
        for row in action["by_kind"]
    }
    assert costs == {
        ("extract", "main"): pytest.approx(4 * 1.5 * 0.5),
        ("extract", "judge"): pytest.approx(8 * 1.5 * 0.5),
        ("write", "main"): pytest.approx(3 * 1.5),
        ("write", "repair"): pytest.approx(1.5),
        ("write", "judge"): pytest.approx(10 * 1.5),
    }
    assert report["actions"]["extract"]["estimated_cost"] == pytest.approx(9.0)
    assert report["actions"]["write"]["estimated_cost"] == pytest.approx(21.0)
    assert report["total"]["estimated_cost"] == pytest.approx(30.0)
    assert (report["priced"], report["unpriced"]) == (True, [])


def test_a_model_the_table_does_not_price_has_no_cost_and_is_named_and_never_costs_zero():
    entries = [
        {"action": "write", "run_id": "run-1", "rows": [_row("main", 2)]},
        {"action": "write", "run_id": "run-1", "rows": [_row("judge", 5, model="other")]},
    ]

    report = usage_report(entries, PRICES, [])

    main, judge = report["actions"]["write"]["by_kind"]
    assert main["estimated_cost"] == pytest.approx(3.0)
    assert judge["estimated_cost"] is None
    assert report["unpriced"] == ["prices.other"]
    assert report["total"]["estimated_cost"] == pytest.approx(3.0), "the sum of what is priced"


def test_a_sum_none_of_whose_rows_is_priced_has_no_cost():
    entries = [{"action": "write", "run_id": "run-1", "rows": [_row("main", 2, model="other")]}]

    report = usage_report(entries, PRICES, [])

    assert report["actions"]["write"]["estimated_cost"] is None
    assert report["total"]["estimated_cost"] is None


def test_actions_are_listed_in_the_order_they_run_and_one_the_order_lacks_comes_last():
    report = usage_report(ENTRIES, {}, ["write"])

    assert list(report["actions"]) == ["write", "extract"]


def test_no_entry_is_an_empty_report():
    assert usage_report([], {}, ["write"]) == {
        "runs": [],
        "actions": {},
        "total": {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "estimated_cost": None,
        },
        "priced": False,
        "unpriced": [],
    }
