"""Nested config blocks reject unknown keys instead of silently dropping them."""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import (
    HitlConfig,
    RetryConfig,
    VersionConfig,
    VersionConsumptionConfig,
)


@pytest.mark.parametrize(
    ("model", "kwargs", "typo"),
    [
        pytest.param(RetryConfig, {"max_retires": 3}, "max_retires", id="retry"),
        pytest.param(VersionConfig, {"parem": "i", "range": [0, 1, 2]}, "parem", id="version"),
        pytest.param(
            VersionConsumptionConfig,
            {"source": "vote_quality", "sorce": "vote_quality"},
            "sorce",
            id="version_consumption",
        ),
        pytest.param(HitlConfig, {"instructions": "Review", "tiemout": 600}, "tiemout", id="hitl"),
    ],
)
def test_nested_block_rejects_typo(model, kwargs, typo):
    with pytest.raises(ValidationError) as excinfo:
        model(**kwargs)
    assert typo in str(excinfo.value)


def test_valid_configs_still_parse():
    assert RetryConfig(max_attempts=3).max_attempts == 3
    assert RetryConfig(base_delay=2, max_delay=30).max_delay == 30
    assert VersionConfig(range=[0, 1, 2]).param == "i"
    assert VersionConsumptionConfig(source="vote_quality").pattern.value == "merge"
    assert HitlConfig(instructions="Review", timeout=600).timeout == 600


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        pytest.param({"base_delay": 0}, "greater than 0", id="zero_base"),
        pytest.param({"base_delay": 301}, "less than or equal to 300", id="base_too_big"),
        pytest.param({"max_delay": 3601}, "less than or equal to 3600", id="max_too_big"),
        pytest.param(
            {"base_delay": 10, "max_delay": 5},
            "max_delay (5) must be at least base_delay (10)",
            id="max_below_base",
        ),
    ],
)
def test_retry_delays_out_of_range_are_refused(kwargs, message):
    with pytest.raises(ValidationError) as excinfo:
        RetryConfig(**kwargs)
    assert message in str(excinfo.value)
