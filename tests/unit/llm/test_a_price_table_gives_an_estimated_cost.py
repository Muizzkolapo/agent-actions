"""The `prices:` block of agent_actions.yml prices a model's tokens, and nothing else does.

A price is per million tokens. The framework ships no price: a usage row whose model has
no entry, or whose entry lacks a price the row needs, has no cost, and the reason names
the key to add. It is never priced at 0.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.llm.config.prices import estimated_cost, parse_prices

PRICES = parse_prices(
    {
        "claude-test": {
            "input": 1.0,
            "output": 5.0,
            "cache_read": 0.1,
            "cache_write": 1.25,
            "batch_discount": 0.5,
        },
        "plain-model": {"input": 2, "output": 8},
    }
)


def _usage(model: str, *, batch: bool = False, **tokens: int) -> dict:
    return {
        "kind": "main",
        "batch": batch,
        "model": model,
        "calls": 1,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        **tokens,
    }


def test_each_kind_of_token_is_charged_at_its_own_price_per_million():
    usage = _usage(
        "claude-test",
        input_tokens=1_000_000,
        output_tokens=200_000,
        cache_read_input_tokens=3_000_000,
        cache_creation_input_tokens=400_000,
    )

    cost, lacking = estimated_cost(PRICES, usage)

    assert lacking is None
    assert cost == pytest.approx(1.0 + 1.0 + 0.3 + 0.5)


def test_a_batch_call_is_charged_less_by_the_batch_discount():
    online = _usage("claude-test", input_tokens=1_000_000, output_tokens=1_000_000)
    batch = {**online, "batch": True}

    assert estimated_cost(PRICES, online) == (pytest.approx(6.0), None)
    assert estimated_cost(PRICES, batch) == (pytest.approx(3.0), None)


def test_a_model_with_no_entry_has_no_cost_and_is_named():
    assert estimated_cost(PRICES, _usage("unpriced", input_tokens=10)) == (None, "prices.unpriced")
    assert estimated_cost({}, _usage("claude-test", input_tokens=10)) == (
        None,
        "prices.claude-test",
    )


def test_a_batch_call_of_a_model_with_no_batch_discount_has_no_cost():
    usage = _usage("plain-model", batch=True, input_tokens=10)

    assert estimated_cost(PRICES, usage) == (None, "prices.plain-model.batch_discount")


@pytest.mark.parametrize(
    ("field", "key"),
    [("cache_read_input_tokens", "cache_read"), ("cache_creation_input_tokens", "cache_write")],
)
def test_cached_tokens_of_a_model_with_no_cache_price_have_no_cost(field, key):
    usage = _usage("plain-model", input_tokens=10, **{field: 5})

    assert estimated_cost(PRICES, usage) == (None, f"prices.plain-model.{key}")


def test_a_price_the_usage_does_not_need_may_be_left_out():
    usage = _usage("plain-model", input_tokens=1_000_000, output_tokens=500_000)

    assert estimated_cost(PRICES, usage) == (pytest.approx(6.0), None)


def test_a_price_of_zero_is_a_price():
    free = parse_prices({"local": {"input": 0, "output": 0}})

    assert estimated_cost(free, _usage("local", input_tokens=10, output_tokens=10)) == (0.0, None)


def test_no_block_is_no_prices():
    assert parse_prices(None) == {}


@pytest.mark.parametrize(
    ("block", "refusal"),
    [
        (["claude-test"], "prices: must be a mapping of model name to its prices"),
        ({"m": 3}, "prices.m: must be a mapping with input and output"),
        ({"m": {"input": 1}}, "prices.m: output is required"),
        ({"m": {"output": 1}}, "prices.m: input is required"),
        ({"m": {"input": 1, "output": 1, "cached": 1}}, "prices.m: unknown key 'cached'"),
        ({"m": {"input": "1.00", "output": 1}}, "prices.m.input: must be a number, 0 or more"),
        ({"m": {"input": -1, "output": 1}}, "prices.m.input: must be a number, 0 or more"),
        ({"m": {"input": 1, "output": True}}, "prices.m.output: must be a number, 0 or more"),
        (
            {"m": {"input": 1, "output": 1, "batch_discount": 50}},
            "prices.m.batch_discount: must be a number from 0 to 1",
        ),
        ({4: {"input": 1, "output": 1}}, "prices: a model name must be text; quote it"),
    ],
)
def test_a_mistake_in_the_block_is_refused_with_its_key(block, refusal):
    with pytest.raises(ConfigValidationError) as refused:
        parse_prices(block)

    assert refusal in str(refused.value)
