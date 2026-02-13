"""Tests for FILE granularity HITL pipeline behavior."""

from unittest.mock import patch

from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.workflow.pipeline import PipelineConfig, ProcessingPipeline


def test_file_mode_hitl_applies_file_decision_to_each_input_record():
    """FILE-mode HITL should preserve all records and attach shared decision payload."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review_data",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
    )

    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1, "question": "Q1"}},
        {"source_guid": "sg-2", "content": {"id": 2, "question": "Q2"}},
    ]
    with patch(
        "agent_actions.workflow.pipeline.run_dynamic_agent",
        return_value=(
            {
                "hitl_status": "approved",
                "user_comment": "",
                "timestamp": "2026-02-12T10:00:00Z",
            },
            True,
        ),
    ):
        results = pipeline._process_file_mode_hitl(input_data, input_data, context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 2
    assert result.data[0]["content"]["hitl_status"] == "approved"
    assert result.data[1]["content"]["hitl_status"] == "approved"
    assert result.data[0]["content"]["question"] == "Q1"
    assert result.data[1]["content"]["question"] == "Q2"
    assert result.data[0]["source_guid"] == "sg-1"
    assert result.data[1]["source_guid"] == "sg-2"


def test_file_mode_hitl_applies_per_record_decisions_when_provided():
    """Per-record review payload should override shared status for each record."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review_data",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
    )

    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
    ]
    with patch(
        "agent_actions.workflow.pipeline.run_dynamic_agent",
        return_value=(
            {
                "hitl_status": "rejected",
                "timestamp": "2026-02-12T10:00:00Z",
                "record_reviews": [
                    {"hitl_status": "approved", "user_comment": "Looks good"},
                    {"hitl_status": "rejected", "user_comment": "Needs revision"},
                ],
            },
            True,
        ),
    ):
        results = pipeline._process_file_mode_hitl(input_data, input_data, context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 2
    assert result.data[0]["content"]["hitl_status"] == "approved"
    assert result.data[0]["content"]["user_comment"] == "Looks good"
    assert result.data[1]["content"]["hitl_status"] == "rejected"
    assert result.data[1]["content"]["user_comment"] == "Needs revision"


def test_file_mode_hitl_preserves_existing_status_field():
    """HITL decision metadata should not overwrite content.status."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review_data",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
    )

    input_data = [{"source_guid": "sg-1", "content": {"id": 1, "status": "pending"}}]
    with patch(
        "agent_actions.workflow.pipeline.run_dynamic_agent",
        return_value=(
            {
                "hitl_status": "approved",
                "status": "approved",
                "user_comment": "ok",
                "record_reviews": [
                    {"hitl_status": "approved", "status": "approved", "user_comment": "r1"}
                ],
            },
            True,
        ),
    ):
        results = pipeline._process_file_mode_hitl(input_data, input_data, context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert result.data[0]["content"]["status"] == "pending"
    assert result.data[0]["content"]["hitl_status"] == "approved"


def test_file_mode_hitl_empty_input_returns_empty_output():
    """Empty data input should produce zero output records, not a synthetic one."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review_data",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
    )

    with patch(
        "agent_actions.workflow.pipeline.run_dynamic_agent",
        return_value=(
            {
                "hitl_status": "approved",
                "user_comment": "",
                "timestamp": "2026-02-12T10:00:00Z",
            },
            True,
        ),
    ):
        results = pipeline._process_file_mode_hitl([], [], context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert result.data == []


def test_file_mode_hitl_preserves_unprocessed_tombstone_markers():
    """Tombstone markers (_unprocessed, metadata) must survive HITL merge."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review_data",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
    )

    input_data = [
        {
            "source_guid": "sg-1",
            "content": {"id": 1},
            "_unprocessed": True,
            "_recovery": {"reason": "tombstone"},
            "metadata": {"agent_type": "tombstone"},
        },
    ]
    with patch(
        "agent_actions.workflow.pipeline.run_dynamic_agent",
        return_value=(
            {
                "hitl_status": "approved",
                "user_comment": "",
                "timestamp": "2026-02-12T10:00:00Z",
            },
            True,
        ),
    ):
        results = pipeline._process_file_mode_hitl(input_data, input_data, context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 1
    item = result.data[0]
    assert item["_unprocessed"] is True
    assert item["_recovery"] == {"reason": "tombstone"}
    assert item["source_guid"] == "sg-1"
    # metadata is present (enrichment may overwrite the value with LLM
    # response metadata, but the field is carried through the merge)
    assert "metadata" in item


def test_file_mode_hitl_preserves_target_id():
    """Input target_id should be preserved through HITL merge."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            agent_config={"kind": "hitl", "granularity": "file"},
            agent_name="review_data",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
    )

    input_data = [
        {
            "source_guid": "sg-1",
            "target_id": "target-abc",
            "content": {"id": 1},
        },
    ]
    with patch(
        "agent_actions.workflow.pipeline.run_dynamic_agent",
        return_value=(
            {
                "hitl_status": "approved",
                "user_comment": "",
                "timestamp": "2026-02-12T10:00:00Z",
            },
            True,
        ),
    ):
        results = pipeline._process_file_mode_hitl(input_data, input_data, context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 1
    assert result.data[0]["target_id"] == "target-abc"
    assert result.data[0]["source_guid"] == "sg-1"


def test_file_mode_hitl_observe_filters_and_orders_fields():
    """context_scope.observe should filter fields shown to HITL and preserve order."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            agent_config={
                "kind": "hitl",
                "granularity": "file",
                "context_scope": {
                    "observe": [
                        "upstream.question",
                        "upstream.answer",
                    ],
                },
            },
            agent_name="review_data",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config=pipeline.config.agent_config,
        agent_name="review_data",
    )

    # Upstream data has extra fields (selectedAnswerer, validity) not in observe
    original_data = [
        {
            "source_guid": "sg-1",
            "content": {
                "question": "What is X?",
                "answer": "X is Y",
                "selectedAnswerer": "Alice",
                "validity": "valid",
            },
        },
        {
            "source_guid": "sg-2",
            "content": {
                "question": "What is Z?",
                "answer": "Z is W",
                "selectedAnswerer": "Bob",
                "validity": "invalid",
            },
        },
    ]

    # Apply the filter as _process_by_strategy would
    filtered = ProcessingPipeline._apply_observe_filter(
        original_data, pipeline.config.agent_config
    )

    # Filtered records should only contain observe fields in defined order
    assert list(filtered[0].keys()) == ["question", "answer"]
    assert list(filtered[1].keys()) == ["question", "answer"]
    assert filtered[0]["question"] == "What is X?"
    assert filtered[1]["answer"] == "Z is W"

    # Verify HITL receives filtered data but merge uses original_data
    captured_context = {}

    def mock_run_dynamic_agent(**kwargs):
        captured_context["context"] = kwargs["context"]
        return (
            {"hitl_status": "approved", "user_comment": "", "timestamp": "2026-02-12T10:00:00Z"},
            True,
        )

    with patch(
        "agent_actions.workflow.pipeline.run_dynamic_agent",
        side_effect=mock_run_dynamic_agent,
    ):
        results = pipeline._process_file_mode_hitl(filtered, original_data, context)

    # HITL UI should have received only filtered fields
    assert list(captured_context["context"][0].keys()) == ["question", "answer"]
    assert "selectedAnswerer" not in captured_context["context"][0]

    # Output merge should preserve ALL original content fields
    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 2
    assert result.data[0]["content"]["question"] == "What is X?"
    assert result.data[0]["content"]["selectedAnswerer"] == "Alice"
    assert result.data[0]["content"]["validity"] == "valid"
    assert result.data[0]["content"]["hitl_status"] == "approved"
    assert result.data[1]["content"]["answer"] == "Z is W"
    assert result.data[1]["content"]["selectedAnswerer"] == "Bob"


def test_apply_observe_filter_no_observe_returns_data_as_is():
    """Without observe config, _apply_observe_filter returns data unchanged."""
    data = [{"content": {"a": 1, "b": 2}}]
    result = ProcessingPipeline._apply_observe_filter(data, {"kind": "hitl"})
    assert result is data


def test_apply_observe_filter_handles_flat_records():
    """Records without content wrapper should be filtered directly."""
    data = [{"question": "Q1", "answer": "A1", "extra": "drop"}]
    config = {
        "context_scope": {
            "observe": ["upstream.answer", "upstream.question"],
        },
    }
    result = ProcessingPipeline._apply_observe_filter(data, config)
    assert list(result[0].keys()) == ["answer", "question"]
    assert result[0]["answer"] == "A1"


def test_apply_observe_filter_wildcard_returns_data_as_is():
    """observe: ['upstream.*'] should return all fields unfiltered."""
    data = [
        {"content": {"question": "Q1", "answer": "A1", "extra": "keep"}},
        {"content": {"question": "Q2", "answer": "A2", "extra": "also keep"}},
    ]
    config = {
        "context_scope": {
            "observe": ["upstream.*"],
        },
    }
    result = ProcessingPipeline._apply_observe_filter(data, config)
    # Wildcard means no filtering — data returned as-is
    assert result is data


def test_apply_observe_filter_mixed_wildcard_and_specific():
    """Wildcard in observe list should trump specific fields and return all."""
    data = [{"content": {"a": 1, "b": 2, "c": 3}}]
    config = {
        "context_scope": {
            "observe": ["upstream.*", "upstream.a"],
        },
    }
    result = ProcessingPipeline._apply_observe_filter(data, config)
    assert result is data
