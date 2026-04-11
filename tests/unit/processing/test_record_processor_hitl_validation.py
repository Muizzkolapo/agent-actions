"""Tests for RecordProcessor configuration validation."""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.processing.processor import RecordProcessor


def test_hitl_record_granularity_raises():
    """HITL actions must use FILE granularity."""
    config = {
        "agent_type": "llm",
        "kind": "hitl",
        "granularity": "record",
        "model_name": "test",
    }
    with pytest.raises(ConfigurationError, match="HITL actions require FILE granularity"):
        RecordProcessor(agent_config=config, agent_name="test_hitl")
