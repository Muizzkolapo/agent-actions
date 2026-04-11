"""Tests for HITL RECORD granularity rejection."""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.workflow.pipeline import PipelineConfig, ProcessingPipeline


def test_record_mode_hitl_raises_configuration_error():
    """HITL with RECORD granularity must raise ConfigurationError."""
    with pytest.raises(ConfigurationError, match="HITL actions require FILE granularity"):
        ProcessingPipeline(
            config=PipelineConfig(
                action_config={
                    "kind": "hitl",
                    "granularity": "record",
                    "model_vendor": "hitl",
                    "context_scope": {"observe": ["source.*"]},
                    "hitl": {
                        "port": 3099,
                        "instructions": "Review each record",
                        "timeout": 60,
                    },
                },
                action_name="review_items",
                idx=0,
            ),
            processor_factory=object(),
        )
