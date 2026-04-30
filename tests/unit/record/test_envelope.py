"""Unit tests for RecordEnvelope — the single authority for record content assembly."""

import pytest

from agent_actions.record.envelope import RecordEnvelope, RecordEnvelopeError
from agent_actions.record.state import (
    InvalidRecordStateError,
    RecordState,
    reason_cascade,
    reason_downstream_reset,
    reason_guard,
)

# ── build() ──────────────────────────────────────────────────────────────────


class TestBuild:
    def test_wraps_under_namespace(self):
        result = RecordEnvelope.build("action_a", {"x": 1})
        assert result["content"] == {"action_a": {"x": 1}}

    def test_preserves_all_upstream(self):
        inp = {
            "source_guid": "g1",
            "content": {"source": {"y": 2}, "summarize": {"z": 3}},
        }
        result = RecordEnvelope.build("review", {"score": 8}, inp)
        assert result["content"]["source"] == {"y": 2}
        assert result["content"]["summarize"] == {"z": 3}
        assert result["content"]["review"] == {"score": 8}

    def test_never_flat_merges(self):
        result = RecordEnvelope.build("action_a", {"x": 1, "y": 2})
        assert "x" not in result["content"]
        assert "y" not in result["content"]
        assert result["content"]["action_a"] == {"x": 1, "y": 2}

    def test_carries_source_guid(self):
        inp = {"source_guid": "guid-42", "content": {}}
        result = RecordEnvelope.build("act", {"v": 1}, inp)
        assert result["source_guid"] == "guid-42"

    def test_no_input_record(self):
        result = RecordEnvelope.build("first", {"a": 1})
        assert result == {"content": {"first": {"a": 1}}, "_state": "active"}
        assert "source_guid" not in result

    def test_empty_action_name_raises(self):
        with pytest.raises(RecordEnvelopeError, match="action_name is required"):
            RecordEnvelope.build("", {"x": 1})

    def test_non_dict_output_raises(self):
        with pytest.raises(RecordEnvelopeError, match="must be a dict"):
            RecordEnvelope.build("action", "not a dict")

    def test_action_name_collision_overwrites(self):
        inp = {"content": {"source": {}, "action_a": {"old": True}}}
        result = RecordEnvelope.build("action_a", {"new": True}, inp)
        assert result["content"]["action_a"] == {"new": True}
        assert "old" not in result["content"]["action_a"]

    def test_does_not_mutate_input_record(self):
        inp = {"source_guid": "g1", "content": {"source": {"x": 1}}}
        original_content = dict(inp["content"])
        RecordEnvelope.build("action_a", {"y": 2}, inp)
        assert inp["content"] == original_content

    def test_input_record_with_non_dict_content_raises(self):
        inp = {"content": "not a dict"}
        with pytest.raises(RecordEnvelopeError, match="must be a dict"):
            RecordEnvelope.build("action", {"x": 1}, inp)

    def test_input_record_with_no_content_key(self):
        inp = {"source_guid": "g1"}
        result = RecordEnvelope.build("action", {"x": 1}, inp)
        assert result["content"] == {"action": {"x": 1}}
        assert result["source_guid"] == "g1"


# ── build_content() ─────────────────────────────────────────────────────────


class TestBuildContent:
    def test_wraps_under_namespace(self):
        result = RecordEnvelope.build_content("action_a", {"x": 1})
        assert result == {"action_a": {"x": 1}}

    def test_preserves_existing(self):
        existing = {"source": {"y": 2}, "summarize": {"z": 3}}
        result = RecordEnvelope.build_content("review", {"score": 8}, existing)
        assert result["source"] == {"y": 2}
        assert result["summarize"] == {"z": 3}
        assert result["review"] == {"score": 8}

    def test_does_not_mutate_existing(self):
        existing = {"source": {"x": 1}}
        RecordEnvelope.build_content("action_a", {"y": 2}, existing)
        assert "action_a" not in existing

    def test_empty_action_name_raises(self):
        with pytest.raises(RecordEnvelopeError, match="action_name is required"):
            RecordEnvelope.build_content("", {"x": 1})


# ── build_skipped() ─────────────────────────────────────────────────────────


class TestBuildSkipped:
    def test_null_namespace(self):
        result = RecordEnvelope.build_skipped("review")
        assert result["content"]["review"] is None

    def test_preserves_upstream(self):
        inp = {
            "source_guid": "g1",
            "content": {"source": {"x": 1}, "summarize": {"y": 2}},
        }
        result = RecordEnvelope.build_skipped("review", inp)
        assert result["content"]["source"] == {"x": 1}
        assert result["content"]["summarize"] == {"y": 2}
        assert result["content"]["review"] is None
        assert result["source_guid"] == "g1"

    def test_does_not_set_unprocessed(self):
        result = RecordEnvelope.build_skipped("action")
        assert "_unprocessed" not in result

    def test_does_not_set_metadata(self):
        result = RecordEnvelope.build_skipped("action")
        assert "metadata" not in result

    def test_empty_action_name_raises(self):
        with pytest.raises(RecordEnvelopeError, match="action_name is required"):
            RecordEnvelope.build_skipped("")


# ── Cross-method interaction ─────────────────────────────────────────────────


class TestInteractions:
    def test_build_then_build_skipped_chain(self):
        """Simulate: action_a produces output, action_b is guard-skipped."""
        r1 = RecordEnvelope.build("action_a", {"x": 1})
        r2 = RecordEnvelope.build_skipped("action_b", r1)
        assert r2["content"]["action_a"] == {"x": 1}
        assert r2["content"]["action_b"] is None

    def test_build_chain_three_actions(self):
        """Simulate: three sequential actions building on each other."""
        r1 = RecordEnvelope.build("source", {"raw": "data"})
        r2 = RecordEnvelope.build("summarize", {"summary": "short"}, r1)
        r3 = RecordEnvelope.build("review", {"score": 9}, r2)
        assert set(r3["content"].keys()) == {"source", "summarize", "review"}
        assert r3["content"]["source"] == {"raw": "data"}
        assert r3["content"]["summarize"] == {"summary": "short"}
        assert r3["content"]["review"] == {"score": 9}


class TestRecordStateFromRecord:
    def test_missing_state_raises(self):
        with pytest.raises(InvalidRecordStateError, match="record\\['_state'\\] is required"):
            RecordState.from_record({})

    def test_valid_string_parsed(self):
        assert RecordState.from_record({"_state": "committed"}) == RecordState.COMMITTED

    def test_invalid_state_raises(self):
        with pytest.raises(InvalidRecordStateError, match="Invalid record _state"):
            RecordState.from_record({"_state": "not_valid"})


# ── transition() / state machine ─────────────────────────────────────────────


class TestTransition:
    def test_records_from_and_to_on_transition(self):
        r = RecordEnvelope.build("act", {"x": 1})
        RecordEnvelope.transition(
            r,
            RecordState.GUARD_SKIPPED,
            action_name="act",
            reason=reason_guard(clause="c", behavior="skip", result=False),
        )
        t = r["_transitions"][-1]
        assert t["from_state"] == RecordState.ACTIVE.value
        assert t["to_state"] == RecordState.GUARD_SKIPPED.value
        assert t["reason"]["type"] == "guard"

    def test_invalid_prior_state_raises(self):
        r: dict = {"content": {}, "_state": "not_a_valid_state"}
        with pytest.raises(RecordEnvelopeError, match="Invalid record _state"):
            RecordEnvelope.transition(
                r,
                RecordState.FAILED,
                action_name="act",
                reason={"type": "error", "error_type": "t", "message": "m"},
            )

    def test_downstream_reset_requires_matching_reason_from_state(self):
        r = {"content": {}, "_state": RecordState.COMMITTED.value}
        with pytest.raises(RecordEnvelopeError, match="from_state"):
            RecordEnvelope.transition(
                r,
                RecordState.ACTIVE,
                action_name="__downstream__",
                reason=reason_downstream_reset(from_state="guard_skipped"),
            )

    def test_downstream_reset_committed_to_active(self):
        r = {"content": {}, "_state": RecordState.COMMITTED.value}
        RecordEnvelope.transition(
            r,
            RecordState.ACTIVE,
            action_name="__downstream__",
            reason=reason_downstream_reset(from_state=RecordState.COMMITTED.value),
        )
        assert r["_state"] == RecordState.ACTIVE.value
        assert r["_transitions"][-1]["from_state"] == RecordState.COMMITTED.value

    def test_no_op_transition_rejected(self):
        r = {"content": {}, "_state": RecordState.ACTIVE.value}
        with pytest.raises(RecordEnvelopeError, match="no-op"):
            RecordEnvelope.transition(
                r,
                RecordState.ACTIVE,
                action_name="act",
                reason={"type": "error", "error_type": "t", "message": "m"},
            )

    def test_cascade_skipped_self_reapply_allowed(self):
        r = {"content": {}, "_state": RecordState.CASCADE_SKIPPED.value}
        RecordEnvelope.transition(
            r,
            RecordState.CASCADE_SKIPPED,
            action_name="act",
            reason=reason_cascade(upstream_action="up", upstream_state="failed"),
        )
        assert r["_transitions"][-1]["from_state"] == RecordState.CASCADE_SKIPPED.value

    def test_passthrough_guard_skip_requires_prior_active(self):
        r = {"content": {}, "_state": RecordState.COMMITTED.value}
        with pytest.raises(RecordEnvelopeError, match="passthrough"):
            RecordEnvelope.transition(
                r,
                RecordState.GUARD_SKIPPED,
                action_name="act",
                reason={"type": "passthrough", "reason": "where", "mode": "batch"},
            )

    def test_unsupported_reason_type_rejected(self):
        r = RecordEnvelope.build("act", {"x": 1})
        with pytest.raises(RecordEnvelopeError, match="Unsupported transition"):
            RecordEnvelope.transition(
                r,
                RecordState.GUARD_SKIPPED,
                action_name="act",
                reason={
                    "type": "custom_unknown",
                },
            )
