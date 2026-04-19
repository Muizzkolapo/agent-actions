"""Tests for FILE granularity HITL pipeline behavior."""

import warnings
from unittest.mock import patch

from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.prompt.context.scope_file_mode import apply_observe_for_file_mode
from agent_actions.workflow.pipeline import PipelineConfig, ProcessingPipeline


def test_file_mode_hitl_applies_file_decision_to_each_input_record():
    """FILE-mode HITL should preserve all records and attach shared decision payload."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            action_config={"kind": "hitl", "granularity": "file"},
            action_name="review_data",
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
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
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
            action_config={"kind": "hitl", "granularity": "file"},
            action_name="review_data",
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
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
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
            action_config={"kind": "hitl", "granularity": "file"},
            action_name="review_data",
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
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
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
            action_config={"kind": "hitl", "granularity": "file"},
            action_name="review_data",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
    )

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
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
            action_config={"kind": "hitl", "granularity": "file"},
            action_name="review_data",
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
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
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
            action_config={"kind": "hitl", "granularity": "file"},
            action_name="review_data",
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
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
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


def test_file_mode_hitl_sets_identity_source_mapping():
    """HITL result must include identity source_mapping for lineage resolution."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            action_config={"kind": "hitl", "granularity": "file"},
            action_name="review_data",
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
        {"source_guid": "sg-3", "content": {"id": 3}},
    ]
    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        return_value=(
            {"hitl_status": "approved", "user_comment": "", "timestamp": "2026-02-12T10:00:00Z"},
            True,
        ),
    ):
        results = pipeline._process_file_mode_hitl(input_data, input_data, context)

    assert len(results) == 1
    result = results[0]
    # source_mapping must be an identity map: output[i] came from input[i]
    assert result.source_mapping == {0: 0, 1: 1, 2: 2}


def test_file_mode_hitl_observe_filters_and_orders_fields():
    """context_scope.observe should filter fields shown to HITL and preserve order."""
    pipeline = ProcessingPipeline(
        config=PipelineConfig(
            action_config={
                "kind": "hitl",
                "granularity": "file",
                "context_scope": {
                    "observe": [
                        "upstream.question",
                        "upstream.answer",
                    ],
                },
            },
            action_name="review_data",
            idx=0,
        ),
        processor_factory=object(),
    )
    context = ProcessingContext(
        agent_config=pipeline.config.action_config,
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

    # Apply the filter as _process_by_strategy would (using new namespace-aware method)
    filtered = apply_observe_for_file_mode(
        data=original_data,
        agent_config=pipeline.config.action_config,
        agent_name="review_data",
    )

    # NiFi enrichment: filtered records are full records with all content preserved
    assert filtered[0]["content"]["question"] == "What is X?"
    assert filtered[0]["content"]["answer"] == "X is Y"
    # All original content fields preserved (no stripping)
    assert filtered[0]["content"]["selectedAnswerer"] == "Alice"
    assert filtered[0]["source_guid"] == "sg-1"
    assert filtered[1]["content"]["answer"] == "Z is W"

    # Verify HITL receives filtered data but merge uses original_data
    captured_context = {}

    def mock_run_dynamic_agent(**kwargs):
        captured_context["context"] = kwargs["context"]
        return (
            {"hitl_status": "approved", "user_comment": "", "timestamp": "2026-02-12T10:00:00Z"},
            True,
        )

    with patch(
        "agent_actions.workflow.pipeline_file_mode.run_dynamic_agent",
        side_effect=mock_run_dynamic_agent,
    ):
        results = pipeline._process_file_mode_hitl(filtered, original_data, context)

    # HITL UI receives full enriched records
    assert captured_context["context"][0]["content"]["question"] == "What is X?"

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
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
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
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
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
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
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
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = ProcessingPipeline._apply_observe_filter(data, config)
    assert result is data


def test_apply_observe_filter_collision_uses_qualified_keys():
    """When two refs share the same bare key, both appear with qualified keys."""
    data = [{"content": {"title": "My Title", "body": "My Body"}}]
    config = {
        "context_scope": {
            "observe": ["dep_a.title", "dep_b.title", "dep_a.body"],
        },
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = ProcessingPipeline._apply_observe_filter(data, config)
    # "title" collides → both refs become qualified output keys
    # "body" is unique → stays bare
    assert list(result[0].keys()) == ["dep_a.title", "dep_b.title", "body"]
    assert result[0]["dep_a.title"] == "My Title"
    assert result[0]["dep_b.title"] == "My Title"
    assert result[0]["body"] == "My Body"


def test_apply_observe_filter_no_collision_stays_bare():
    """When all refs have unique bare keys, output keys remain bare."""
    data = [{"content": {"question": "Q1", "answer": "A1"}}]
    config = {
        "context_scope": {
            "observe": ["upstream.question", "upstream.answer"],
        },
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = ProcessingPipeline._apply_observe_filter(data, config)
    assert list(result[0].keys()) == ["question", "answer"]


def test_apply_observe_filter_invalid_ref_does_not_misalign_pairs():
    """Invalid refs between valid ones must not shift collision pairing."""
    data = [{"content": {"title": "T", "body": "B"}}]
    config = {
        "context_scope": {
            "observe": ["dep_a.title", "bad_ref_no_dot", "dep_b.title", "dep_a.body"],
        },
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = ProcessingPipeline._apply_observe_filter(data, config)
    # "bad_ref_no_dot" is dropped; remaining refs pair correctly
    # "title" still collides → qualified keys
    assert list(result[0].keys()) == ["dep_a.title", "dep_b.title", "body"]
    assert result[0]["dep_a.title"] == "T"
    assert result[0]["dep_b.title"] == "T"
    assert result[0]["body"] == "B"


def test_apply_observe_filter_emits_deprecation_warning():
    """_apply_observe_filter should emit a DeprecationWarning."""
    data = [{"content": {"a": 1}}]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        ProcessingPipeline._apply_observe_filter(data, {"kind": "hitl"})
    dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(dep_warnings) == 1
    assert "apply_observe_for_file_mode" in str(dep_warnings[0].message)


# --- Tests for apply_observe_for_file_mode ---


def test_new_observe_no_observe_returns_data_as_is():
    """Without observe config, apply_observe_for_file_mode returns data unchanged."""
    data = [{"content": {"a": 1, "b": 2}}]
    result = apply_observe_for_file_mode(
        data=data, agent_config={"kind": "hitl"}, agent_name="test"
    )
    assert result is data


def test_new_observe_handles_flat_records():
    """Records without content wrapper: no cross-ns refs → fast path returns as-is."""
    data = [{"question": "Q1", "answer": "A1", "extra": "keep"}]
    config = {"context_scope": {"observe": ["upstream.answer", "upstream.question"]}}
    result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
    # No cross-namespace refs → fast path returns data unmodified
    assert result[0]["answer"] == "A1"
    assert result[0]["question"] == "Q1"
    assert result[0]["extra"] == "keep"


def test_new_observe_wildcard_returns_all_content_fields():
    """observe: ['upstream.*'] should return full records with all content preserved."""
    data = [
        {"content": {"question": "Q1", "answer": "A1", "extra": "keep"}},
        {"content": {"question": "Q2", "answer": "A2", "extra": "also keep"}},
    ]
    config = {"context_scope": {"observe": ["upstream.*"]}}
    result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
    assert result[0]["content"] == {"question": "Q1", "answer": "A1", "extra": "keep"}
    assert result[1]["content"] == {"question": "Q2", "answer": "A2", "extra": "also keep"}


def test_new_observe_collision_uses_qualified_keys():
    """When two refs share the same bare key with NiFi enrichment.

    NOTE: No agent_indices/file_path provided, so dep_b cannot load
    historically and falls through to content lookup. With NiFi enrichment,
    the original content fields are preserved as-is (no qualified key
    renaming for input-source fields). The original 'title' and 'body'
    remain in content.
    """
    data = [{"content": {"title": "My Title", "body": "My Body"}}]
    config = {
        "context_scope": {
            "observe": ["dep_a.title", "dep_b.title", "dep_a.body"],
        },
    }
    result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
    # NiFi enrichment: full record with original content preserved
    assert result[0]["content"]["title"] == "My Title"
    assert result[0]["content"]["body"] == "My Body"


def test_new_observe_no_collision_stays_bare():
    """When all refs have unique bare keys, content fields are preserved."""
    data = [{"content": {"question": "Q1", "answer": "A1"}}]
    config = {"context_scope": {"observe": ["upstream.question", "upstream.answer"]}}
    result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
    # NiFi enrichment: full record returned with content preserved
    assert result[0]["content"]["question"] == "Q1"
    assert result[0]["content"]["answer"] == "A1"


def test_new_observe_invalid_ref_does_not_misalign_pairs():
    """Invalid refs between valid ones must not shift collision pairing."""
    data = [{"content": {"title": "T", "body": "B"}}]
    config = {
        "context_scope": {
            "observe": ["dep_a.title", "bad_ref_no_dot", "dep_b.title", "dep_a.body"],
        },
    }
    result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
    # NiFi enrichment: full record with original content preserved
    assert result[0]["content"]["title"] == "T"
    assert result[0]["content"]["body"] == "B"
