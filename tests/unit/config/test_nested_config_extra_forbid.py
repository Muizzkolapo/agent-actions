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
    assert VersionConfig(range=[0, 1, 2]).param == "i"
    assert VersionConsumptionConfig(source="vote_quality").pattern.value == "merge"
    assert HitlConfig(instructions="Review", timeout=600).timeout == 600
