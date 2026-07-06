"""Nested config blocks reject unknown keys instead of silently dropping them."""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import (
    HitlConfig,
    RetryConfig,
    VersionConfig,
    VersionConsumptionConfig,
)


def test_retry_rejects_typo():
    with pytest.raises(ValidationError) as excinfo:
        RetryConfig(max_retires=3)
    assert "max_retires" in str(excinfo.value)


def test_version_rejects_typo():
    with pytest.raises(ValidationError) as excinfo:
        VersionConfig(parem="i", range=[0, 1, 2])
    assert "parem" in str(excinfo.value)


def test_version_consumption_rejects_typo():
    with pytest.raises(ValidationError) as excinfo:
        VersionConsumptionConfig(source="vote_quality", sorce="vote_quality")
    assert "sorce" in str(excinfo.value)


def test_hitl_rejects_typo():
    with pytest.raises(ValidationError) as excinfo:
        HitlConfig(instructions="Review", tiemout=600)
    assert "tiemout" in str(excinfo.value)


def test_valid_configs_still_parse():
    assert RetryConfig(max_attempts=3).max_attempts == 3
    assert VersionConfig(range=[0, 1, 2]).param == "i"
    assert VersionConsumptionConfig(source="vote_quality").pattern.value == "merge"
    assert HitlConfig(instructions="Review", timeout=600).timeout == 600
