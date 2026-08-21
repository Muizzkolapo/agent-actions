"""Tests for FILE granularity HITL pipeline behavior."""

import logging
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
    """Tombstone markers (_recovery, metadata) must survive HITL merge."""
    input_data = [
        {
            "source_guid": "sg-1",
            "content": {"id": 1},
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


def test_file_mode_hitl_server_error_is_not_broadcast_as_a_decision():
    """A failed approval UI must fail the action, never be applied as a verdict.

    The server emits ``hitl_status="error"`` when it cannot bind a port. Treating
    that as a decision stamps every record reviewed and lets the run report
    success while downstream guards silently discard the whole dataset.
    """
    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
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
                    "hitl_status": "error",
                    "user_comment": "Server failed to start: [Errno 48] Address already in use",
                    "timestamp": "2026-02-12T10:00:00Z",
                },
                True,
            ),
        ),
        pytest.raises(AgentActionsError, match="error"),
    ):
        HITLStrategy().invoke(input_data, context)


def test_file_mode_hitl_unknown_status_is_not_broadcast_as_a_decision():
    """Only approved/rejected are decisions; anything else must fail the action."""
    input_data = [{"source_guid": "sg-1", "content": {"id": 1}}]
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
        source_data=input_data,
    )

    with (
        patch(
            "agent_actions.processing.strategies.hitl.run_dynamic_agent",
            return_value=(
                {"hitl_status": "pending", "timestamp": "2026-02-12T10:00:00Z"},
                True,
            ),
        ),
        pytest.raises(AgentActionsError, match="pending"),
    ):
        HITLStrategy().invoke(input_data, context)


def test_file_mode_hitl_per_record_non_decision_status_raises():
    """The allowlist must hold per record, not only for the file-level status.

    Per-record reviews overwrite the broadcast status, so a non-decision value
    here reaches records through the same door layer 1 closed one level up.
    """
    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
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
                    "hitl_status": "approved",
                    "record_reviews": [
                        {"hitl_status": "approved", "user_comment": ""},
                        {"hitl_status": "error", "user_comment": "ui died"},
                    ],
                },
                True,
            ),
        ),
        pytest.raises(AgentActionsError, match="error"),
    ):
        HITLStrategy().invoke(input_data, context)


def test_file_mode_hitl_rejected_file_decision_still_succeeds():
    """Anchor: real decisions keep flowing through with their shape unchanged."""
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
                "user_comment": "not usable",
                "timestamp": "2026-02-12T10:00:00Z",
            },
            True,
        ),
    ):
        results = HITLStrategy().invoke(input_data, context)

    assert len(results) == 1
    assert results[0].status == ProcessingStatus.SUCCESS
    assert len(results[0].data) == 2
    for record in results[0].data:
        assert record["content"]["review_data"]["hitl_status"] == "rejected"
        assert record["content"]["review_data"]["user_comment"] == "not usable"
        assert record["content"]["review_data"]["timestamp"] == "2026-02-12T10:00:00Z"


def test_auto_approve_bypass_is_announced_at_warning_level(monkeypatch):
    """The review bypass must be impossible to miss in an otherwise normal run.

    ``AGAC_HITL_AUTO_APPROVE`` fabricates the approval a human never gave. It is
    needed by the smoke ring, but at info level a stale shell export silently
    turns every approval gate in every workflow into a rubber stamp.

    Captures on the module logger rather than via ``caplog``: LoggerFactory sets
    ``propagate = False`` on the ``agent_actions`` logger, so once any earlier
    test configures logging, records never reach caplog's root handler.
    """
    monkeypatch.setenv("AGAC_HITL_AUTO_APPROVE", "true")
    input_data = [
        {"source_guid": "sg-1", "content": {"id": 1}},
        {"source_guid": "sg-2", "content": {"id": 2}},
    ]
    context = ProcessingContext(
        agent_config={"kind": "hitl", "granularity": "file"},
        agent_name="review_data",
        source_data=input_data,
    )

    emitted: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            emitted.append(record)

    hitl_logger = logging.getLogger("agent_actions.processing.strategies.hitl")
    handler = _Capture(level=logging.WARNING)
    original_level = hitl_logger.level
    hitl_logger.addHandler(handler)
    hitl_logger.setLevel(logging.WARNING)
    try:
        results = HITLStrategy().invoke(input_data, context)
    finally:
        hitl_logger.removeHandler(handler)
        hitl_logger.setLevel(original_level)

    bypass_warnings = [
        record for record in emitted if "AGAC_HITL_AUTO_APPROVE" in record.getMessage()
    ]
    assert bypass_warnings, "bypass must be announced at WARNING, not info"
    assert all(record.levelno >= logging.WARNING for record in bypass_warnings)

    # Anchor: the bypass itself still behaves exactly as before.
    assert results[0].status == ProcessingStatus.SUCCESS
    assert len(results[0].data) == 2
    for record in results[0].data:
        assert record["content"]["review_data"]["hitl_status"] == "approved"


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
    filtered, _ = apply_context_scope_for_records(
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

    # Verify HITL receives only observe-filtered fields (flat dict, not full bus)
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

    # HITL UI receives only observed fields — flat dict, no full bus
    assert captured_context["context"][0] == {"question": "What is X?", "answer": "X is Y"}
    assert captured_context["context"][1] == {"question": "What is Z?", "answer": "Z is W"}
    # Non-observed fields must NOT be shown to the reviewer
    assert "selectedAnswerer" not in captured_context["context"][0]
    assert "validity" not in captured_context["context"][0]

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


def test_file_mode_hitl_no_observe_flattens_all_namespaces():
    """Without observe config, HITL receives all content fields flattened."""
    action_config = {"kind": "hitl", "granularity": "file"}

    records = [
        {
            "source_guid": "sg-1",
            "content": {
                "upstream": {"question": "What?", "answer": "Yes"},
            },
        },
    ]

    context = ProcessingContext(
        agent_config=action_config,
        agent_name="review",
        source_data=records,
    )

    captured_context = {}

    def mock_run(**kwargs):
        captured_context["context"] = kwargs["context"]
        return ({"hitl_status": "approved", "timestamp": "2026-01-01T00:00:00Z"}, True)

    with patch(
        "agent_actions.processing.strategies.hitl.run_dynamic_agent",
        side_effect=mock_run,
    ):
        HITLStrategy().invoke(records, context)

    # All fields flattened (no observe = show everything)
    assert captured_context["context"][0] == {"question": "What?", "answer": "Yes"}


def test_file_mode_hitl_empty_observe_gates_all():
    """observe: [] is a declared gate — the reviewer sees no business fields.

    Inverted for issue #871. The previous assertion pinned flatten-all and
    justified it by the implementation ("Empty observe = falsy"), not by intent,
    which contradicts the contract the prompt path documents at
    scope_application.py:152-153: no directive keys at all = pass everything
    through, distinct from {"observe": []} = gate to framework namespaces only.
    """
    action_config = {
        "kind": "hitl",
        "granularity": "file",
        "context_scope": {"observe": []},
    }

    records = [
        {
            "source_guid": "sg-1",
            "content": {"upstream": {"question": "What?", "answer": "Yes"}},
        },
    ]

    context = ProcessingContext(
        agent_config=action_config,
        agent_name="review",
        source_data=records,
    )

    captured_context = {}

    def mock_run(**kwargs):
        captured_context["context"] = kwargs["context"]
        return ({"hitl_status": "approved", "timestamp": "2026-01-01T00:00:00Z"}, True)

    with patch(
        "agent_actions.processing.strategies.hitl.run_dynamic_agent",
        side_effect=mock_run,
    ):
        HITLStrategy().invoke(records, context)

    # Declared gate — nothing upstream reaches the reviewer.
    assert captured_context["context"][0] == {}


def test_file_mode_hitl_intentional_gate_does_not_warn(caplog):
    """`observe: []` gates on purpose — no "check your observe references" advice.

    The empty-payload warning exists to catch refs that match no upstream
    namespace. An author who declared an empty gate has no refs to check, so the
    advice would be misdirection.
    """
    action_config = {"kind": "hitl", "granularity": "file", "context_scope": {"observe": []}}
    records = [{"source_guid": "sg-1", "content": {"upstream": {"question": "What?"}}}]
    context = ProcessingContext(
        agent_config=action_config, agent_name="review", source_data=records
    )

    def mock_run(**kwargs):
        return ({"hitl_status": "approved", "timestamp": "2026-01-01T00:00:00Z"}, True)

    with caplog.at_level(logging.WARNING):
        with patch(
            "agent_actions.processing.strategies.hitl.run_dynamic_agent",
            side_effect=mock_run,
        ):
            HITLStrategy().invoke(records, context)

    assert not [r for r in caplog.records if "no visible fields" in r.getMessage()]


def test_file_mode_hitl_bad_namespace_in_observe_warns():
    """Misspelled namespace in observe produces empty context and logs warning."""
    action_config = {
        "kind": "hitl",
        "granularity": "file",
        "context_scope": {"observe": ["nonexistent.field"]},
    }

    records = [
        {
            "source_guid": "sg-1",
            "content": {"upstream": {"question": "What?"}},
        },
    ]

    context = ProcessingContext(
        agent_config=action_config,
        agent_name="review",
        source_data=records,
    )

    captured_context = {}

    def mock_run(**kwargs):
        captured_context["context"] = kwargs["context"]
        return ({"hitl_status": "approved", "timestamp": "2026-01-01T00:00:00Z"}, True)

    with (
        patch(
            "agent_actions.processing.strategies.hitl.run_dynamic_agent",
            side_effect=mock_run,
        ),
        patch("agent_actions.processing.strategies.hitl.logger") as mock_logger,
    ):
        HITLStrategy().invoke(records, context)

    # Reviewer sees empty dict
    assert captured_context["context"][0] == {}
    mock_logger.warning.assert_called_once()


# --- Tests for apply_context_scope_for_records ---


def test_no_observe_returns_data_as_is():
    """Without observe config, apply_context_scope_for_records returns data unchanged."""
    data = [{"content": {"a": 1, "b": 2}}]
    result, _ = apply_context_scope_for_records(records=data, context_scope={}, action_name="test")
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
    result, _ = apply_context_scope_for_records(
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
    result, _ = apply_context_scope_for_records(
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
    result, _ = apply_context_scope_for_records(
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
    result, _ = apply_context_scope_for_records(
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
    result, _ = apply_context_scope_for_records(
        records=data, context_scope=context_scope, action_name="test"
    )
    # "title" collides → qualified
    assert result[0]["content"]["dep_a.title"] == "T"
    assert result[0]["content"]["dep_b.title"] == "T2"
    assert result[0]["content"]["body"] == "B"
