"""Smoke test for RECORD granularity HITL pipeline behaviour."""

from unittest.mock import patch

from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.workflow.pipeline import PipelineConfig, ProcessingPipeline


def test_record_mode_hitl_processes_each_record_independently():
    """RECORD-mode HITL invokes the HITL client once per input record."""
    pipeline = ProcessingPipeline(
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

    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1, "question": "Q1"}},
        {"source_guid": "sg-2", "content": {"id": 2, "question": "Q2"}},
    ]

    context = ProcessingContext(
        agent_config=pipeline.config.action_config,
        agent_name="review_items",
    )

    # Mock run_dynamic_agent at the invocation layer (record path)
    call_count = {"n": 0}

    def mock_run_dynamic_agent(*args, **kwargs):
        call_count["n"] += 1
        return (
            [{"hitl_status": "approved", "user_comment": "", "timestamp": "2026-02-13T10:00:00Z"}],
            True,
        )

    with patch(
        "agent_actions.processing.helpers.run_dynamic_agent",
        side_effect=mock_run_dynamic_agent,
    ):
        results = pipeline.record_processor.process_batch(input_data, context)

    # Each input record should produce one result
    assert len(results) == 2
    assert all(r.status == ProcessingStatus.SUCCESS for r in results)
    # HITL client was invoked once per record
    assert call_count["n"] == 2
