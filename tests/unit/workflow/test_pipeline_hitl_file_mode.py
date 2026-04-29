"""Tests for FILE granularity HITL pipeline behavior."""

from unittest.mock import patch

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.processing.strategies.hitl import HITLStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.prompt.context.scope_application import apply_context_scope_for_records


def test_file_mode_hitl_applies_file_decision_to_each_input_record():
    """FILE-mode HITL should preserve all records and attach shared decision payload."""
    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1, "question": "Q1"}},
        {"source_guid": "sg-2", "content": {"id": 2, "question": "Q2"}},
    ]
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
        source_data=input_data,
    )

    with patch(
        "agent_actions.processing.strategies.hitl.run_dynamic_agent",
        return_value=(
            {
                "hitl_status": "approved",
                "user_comment": "",
                "timestamp": "2026-02-12T10:00:00Z",
            },
            True,
        ),
    ):
        results = HITLStrategy().invoke(input_data, context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 2
    # HITL output is namespaced under the action name
    assert result.data[0]["content"]["review_data"]["hitl_status"] == "approved"
    assert result.data[1]["content"]["review_data"]["hitl_status"] == "approved"
    # Upstream content fields preserved alongside the HITL namespace
    assert result.data[0]["content"]["id"] == 1
    assert result.data[0]["content"]["question"] == "Q1"
    assert result.data[1]["content"]["id"] == 2
    assert result.data[1]["content"]["question"] == "Q2"
    assert result.data[0]["source_guid"] == "sg-1"
    assert result.data[1]["source_guid"] == "sg-2"


def test_file_mode_hitl_applies_per_record_decisions_when_provided():
    """Per-record review payload should override shared status for each record."""
    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
    ]
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
        source_data=input_data,
    )

    with patch(
        "agent_actions.processing.strategies.hitl.run_dynamic_agent",
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
        results = HITLStrategy().invoke(input_data, context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 2
    # Per-record review fields are under the action namespace
    assert result.data[0]["content"]["review_data"]["hitl_status"] == "approved"
    assert result.data[0]["content"]["review_data"]["user_comment"] == "Looks good"
    assert result.data[1]["content"]["review_data"]["hitl_status"] == "rejected"
    assert result.data[1]["content"]["review_data"]["user_comment"] == "Needs revision"


def test_file_mode_hitl_preserves_existing_status_field():
    """HITL decision metadata should not overwrite content.status."""
    input_data = [{"source_guid": "sg-1", "content": {"id": 1, "status": "pending"}}]
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
        source_data=input_data,
    )

    with patch(
        "agent_actions.processing.strategies.hitl.run_dynamic_agent",
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
        results = HITLStrategy().invoke(input_data, context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    # Upstream 'status' field is preserved in existing content
    assert result.data[0]["content"]["status"] == "pending"
    # HITL decision is under the action namespace — no collision
    assert result.data[0]["content"]["review_data"]["hitl_status"] == "approved"


def test_file_mode_hitl_empty_input_returns_empty_output():
    """Empty data input should produce zero output records, not a synthetic one."""
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
        source_data=[],
    )

    with patch(
        "agent_actions.processing.strategies.hitl.run_dynamic_agent",
        return_value=(
            {
                "hitl_status": "approved",
                "user_comment": "",
                "timestamp": "2026-02-12T10:00:00Z",
            },
            True,
        ),
    ):
        results = HITLStrategy().invoke([], context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert result.data == []


def test_file_mode_hitl_preserves_unprocessed_tombstone_markers():
    """Tombstone markers (_unprocessed, metadata) must survive HITL merge."""
    input_data = [
        {
            "source_guid": "sg-1",
            "content": {"id": 1},
            "_unprocessed": True,
            "_recovery": {"reason": "tombstone"},
            "metadata": {"agent_type": "tombstone"},
        },
    ]
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
        source_data=input_data,
    )

    with patch(
        "agent_actions.processing.strategies.hitl.run_dynamic_agent",
        return_value=(
            {
                "hitl_status": "approved",
                "user_comment": "",
                "timestamp": "2026-02-12T10:00:00Z",
            },
            True,
        ),
    ):
        results = HITLStrategy().invoke(input_data, context)

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
    input_data = [
        {
            "source_guid": "sg-1",
            "target_id": "target-abc",
            "content": {"id": 1},
        },
    ]
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
        source_data=input_data,
    )

    with patch(
        "agent_actions.processing.strategies.hitl.run_dynamic_agent",
        return_value=(
            {
                "hitl_status": "approved",
                "user_comment": "",
                "timestamp": "2026-02-12T10:00:00Z",
            },
            True,
        ),
    ):
        results = HITLStrategy().invoke(input_data, context)

    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 1
    assert result.data[0]["target_id"] == "target-abc"
    assert result.data[0]["source_guid"] == "sg-1"


def test_file_mode_hitl_sets_identity_source_mapping():
    """HITL result must include identity source_mapping for lineage resolution."""
    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
        {"source_guid": "sg-3", "content": {"id": 3}},
    ]
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
        source_data=input_data,
    )

    with patch(
        "agent_actions.processing.strategies.hitl.run_dynamic_agent",
        return_value=(
            {"hitl_status": "approved", "user_comment": "", "timestamp": "2026-02-12T10:00:00Z"},
            True,
        ),
    ):
        results = HITLStrategy().invoke(input_data, context)

    assert len(results) == 1
    result = results[0]
    # source_mapping must be an identity map: output[i] came from input[i]
    assert result.source_mapping == {0: 0, 1: 1, 2: 2}


def test_file_mode_hitl_timeout_raises_with_record_count():
    """HITL timeout raises AgentActionsError with correct record count."""
    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
        {"source_guid": "sg-3", "content": {"id": 3}},
    ]
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
        source_data=input_data,
    )

    with (
        patch(
            "agent_actions.processing.strategies.hitl.run_dynamic_agent",
            return_value=(
                {
                    "hitl_status": "timeout",
                    "record_reviews": [{"hitl_status": "approved"}, None, None],
                },
                True,
            ),
        ),
        pytest.raises(AgentActionsError, match="1/3 records reviewed"),
    ):
        HITLStrategy().invoke(input_data, context)


def test_file_mode_hitl_observe_filters_and_orders_fields():
    """context_scope.observe should filter fields shown to HITL and preserve order."""
    action_config = {
        "kind": "hitl",
        "granularity": "file",
        "context_scope": {
            "observe": [
                "upstream.question",
                "upstream.answer",
            ],
        },
    }

    # Upstream data with namespaced content (additive model)
    original_data = [
        {
            "source_guid": "sg-1",
            "content": {
                "upstream": {
                    "question": "What is X?",
                    "answer": "X is Y",
                    "selectedAnswerer": "Alice",
                    "validity": "valid",
                },
            },
        },
        {
            "source_guid": "sg-2",
            "content": {
                "upstream": {
                    "question": "What is Z?",
                    "answer": "Z is W",
                    "selectedAnswerer": "Bob",
                    "validity": "invalid",
                },
            },
        },
    ]

    # Apply the filter using unified context_scope
    context_scope = action_config.get("context_scope", {})
    filtered = apply_context_scope_for_records(
        records=original_data,
        context_scope=context_scope,
        action_name="review_data",
    )

    # Enrichment: flat observed keys injected, all namespaces preserved
    assert filtered[0]["content"]["question"] == "What is X?"
    assert filtered[0]["content"]["answer"] == "X is Y"
    # Non-observed fields preserved in namespace (not as flat keys)
    assert filtered[0]["content"]["upstream"]["selectedAnswerer"] == "Alice"
    assert filtered[0]["source_guid"] == "sg-1"
    assert filtered[1]["content"]["answer"] == "Z is W"

    context = ProcessingContext(
        agent_config=action_config,
        agent_name="review_data",
        source_data=original_data,
    )

    # Verify HITL receives filtered data but merge uses original_data
    captured_context = {}

    def mock_run_dynamic_agent(**kwargs):
        captured_context["context"] = kwargs["context"]
        return (
            {"hitl_status": "approved", "user_comment": "", "timestamp": "2026-02-12T10:00:00Z"},
            True,
        )

    with patch(
        "agent_actions.processing.strategies.hitl.run_dynamic_agent",
        side_effect=mock_run_dynamic_agent,
    ):
        results = HITLStrategy().invoke(filtered, context)

    # HITL UI receives full enriched records
    assert captured_context["context"][0]["content"]["question"] == "What is X?"

    # Output merge should preserve ALL original content fields
    assert len(results) == 1
    result = results[0]
    assert result.status == ProcessingStatus.SUCCESS
    assert len(result.data) == 2
    # Upstream content fields preserved in namespace
    assert result.data[0]["content"]["upstream"]["question"] == "What is X?"
    assert result.data[0]["content"]["upstream"]["selectedAnswerer"] == "Alice"
    assert result.data[0]["content"]["upstream"]["validity"] == "valid"
    # HITL decision under the action namespace
    assert result.data[0]["content"]["review_data"]["hitl_status"] == "approved"
    assert result.data[1]["content"]["upstream"]["answer"] == "Z is W"
    assert result.data[1]["content"]["upstream"]["selectedAnswerer"] == "Bob"


# --- Tests for apply_context_scope_for_records ---


def test_no_observe_returns_data_as_is():
    """Without observe config, apply_context_scope_for_records returns data unchanged."""
    data = [{"content": {"a": 1, "b": 2}}]
    result = apply_context_scope_for_records(records=data, context_scope={}, action_name="test")
    assert result is data


def test_observe_extracts_from_namespace():
    """Observe refs extract fields from namespaced content as flat keys."""
    data = [
        {
            "content": {
                "upstream": {"question": "Q1", "answer": "A1", "extra": "keep"},
            },
        },
    ]
    context_scope = {"observe": ["upstream.question", "upstream.answer"]}
    result = apply_context_scope_for_records(
        records=data, context_scope=context_scope, action_name="test"
    )
    assert result[0]["content"]["question"] == "Q1"
    assert result[0]["content"]["answer"] == "A1"
    # Original namespace preserved
    assert result[0]["content"]["upstream"]["extra"] == "keep"


def test_wildcard_observe_preserves_all_content():
    """observe: ['upstream.*'] extracts all fields as flat keys."""
    data = [
        {"content": {"upstream": {"question": "Q1", "answer": "A1", "extra": "keep"}}},
        {"content": {"upstream": {"question": "Q2", "answer": "A2", "extra": "also keep"}}},
    ]
    context_scope = {"observe": ["upstream.*"]}
    result = apply_context_scope_for_records(
        records=data, context_scope=context_scope, action_name="test"
    )
    assert result[0]["content"]["question"] == "Q1"
    assert result[0]["content"]["answer"] == "A1"
    assert result[1]["content"]["question"] == "Q2"
    assert result[1]["content"]["answer"] == "A2"


def test_collision_uses_qualified_keys():
    """When two namespaces have same field name, keys are namespace-qualified."""
    data = [
        {
            "content": {
                "dep_a": {"title": "Title from A", "body": "Body A"},
                "dep_b": {"title": "Title from B"},
            },
        },
    ]
    context_scope = {"observe": ["dep_a.title", "dep_b.title", "dep_a.body"]}
    result = apply_context_scope_for_records(
        records=data, context_scope=context_scope, action_name="test"
    )
    assert result[0]["content"]["dep_a.title"] == "Title from A"
    assert result[0]["content"]["dep_b.title"] == "Title from B"
    assert result[0]["content"]["body"] == "Body A"


def test_no_collision_stays_bare():
    """When all refs have unique bare keys, flat keys are unqualified."""
    data = [
        {
            "content": {
                "upstream": {"question": "Q1", "answer": "A1"},
            },
        },
    ]
    context_scope = {"observe": ["upstream.question", "upstream.answer"]}
    result = apply_context_scope_for_records(
        records=data, context_scope=context_scope, action_name="test"
    )
    assert result[0]["content"]["question"] == "Q1"
    assert result[0]["content"]["answer"] == "A1"


def test_invalid_ref_does_not_misalign_pairs():
    """Invalid refs between valid ones must not shift collision pairing."""
    data = [
        {
            "content": {
                "dep_a": {"title": "T", "body": "B"},
                "dep_b": {"title": "T2"},
            },
        },
    ]
    context_scope = {"observe": ["dep_a.title", "bad_ref_no_dot", "dep_b.title", "dep_a.body"]}
    result = apply_context_scope_for_records(
        records=data, context_scope=context_scope, action_name="test"
    )
    # "title" collides → qualified
    assert result[0]["content"]["dep_a.title"] == "T"
    assert result[0]["content"]["dep_b.title"] == "T2"
    assert result[0]["content"]["body"] == "B"
