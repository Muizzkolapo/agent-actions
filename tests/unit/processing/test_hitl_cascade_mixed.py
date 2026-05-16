"""Test HITL strategy with cascade-blocked records mixed in.

Proves that when cascade-blocked records are present in input,
HITL review decisions are applied to the correct active records
by position (not misattributed to quarantined records).
"""

from typing import Any
from unittest.mock import patch

from agent_actions.processing.strategies.hitl import HITLStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from tests.helpers.cascade_helpers import make_record as _record


def _make_context(agent_name: str = "hitl_review", **kwargs) -> ProcessingContext:
    config: dict[str, Any] = {
        "agent_type": agent_name,
        "name": agent_name,
        "context_scope": {},
    }
    return ProcessingContext(
        agent_config=config,
        agent_name=agent_name,
        **kwargs,
    )


class TestHITLCascadeMixed:
    """HITL with mixed active + cascade-blocked records."""

    def test_reviews_applied_to_correct_records(self):
        """Input: [R1 active, R2 failed, R3 active].
        HITL sees [R1, R3] (processable only).
        Returns record_reviews for [R1, R3].
        R1 gets review_for_R1, R3 gets review_for_R3.
        R2 appears only as a quarantined tombstone.
        """
        r1 = _record("r1", "active")
        r2 = _record("r2", "failed")
        r3 = _record("r3", "active")

        context = _make_context()
        # source_data is set by UnifiedProcessor — includes all passing records
        context.source_data = [r1, r2, r3]

        hitl_response = {
            "hitl_status": "approved",
            "record_reviews": [
                {"hitl_status": "approved", "user_comment": "R1 looks good"},
                {"hitl_status": "rejected", "user_comment": "R3 needs work"},
            ],
        }

        with patch(
            "agent_actions.processing.strategies.hitl.run_dynamic_agent",
            return_value=([hitl_response], True),
        ):
            results = HITLStrategy().invoke([r1, r2, r3], context)

        # Should have quarantined results + 1 SUCCESS result
        unprocessed = [r for r in results if r.status == ProcessingStatus.UNPROCESSED]
        successes = [r for r in results if r.status == ProcessingStatus.SUCCESS]
        assert len(unprocessed) == 1  # R2 quarantined
        assert unprocessed[0].source_guid == "r2"

        assert len(successes) == 1
        success_data = successes[0].data
        # Should have exactly 2 records (R1 and R3), not 3
        assert len(success_data) == 2

        # R1 should have "R1 looks good" comment
        r1_out = success_data[0]
        r1_content = r1_out.get("content", {})
        hitl_ns = r1_content.get("hitl_review", {})
        assert hitl_ns.get("user_comment") == "R1 looks good"

        # R3 should have "R3 needs work" comment (not misattributed to R2)
        r3_out = success_data[1]
        r3_content = r3_out.get("content", {})
        hitl_ns_r3 = r3_content.get("hitl_review", {})
        assert hitl_ns_r3.get("user_comment") == "R3 needs work"

    def test_all_quarantined_returns_only_tombstones(self):
        """When all records are cascade-blocked, no HITL invocation happens."""
        r1 = _record("r1", "failed")
        r2 = _record("r2", "exhausted")

        context = _make_context()
        context.source_data = [r1, r2]

        # run_dynamic_agent should NOT be called
        with patch(
            "agent_actions.processing.strategies.hitl.run_dynamic_agent",
        ) as mock_agent:
            results = HITLStrategy().invoke([r1, r2], context)

        mock_agent.assert_not_called()
        assert len(results) == 2
        assert all(r.status == ProcessingStatus.UNPROCESSED for r in results)

    def test_interleaved_cascade_blocked_at_start_and_end(self):
        """Input: [R1 failed, R2 active, R3 failed, R4 active, R5 failed].
        Processable: [R2, R4]. Reviews indexed correctly despite gaps.
        """
        r1 = _record("r1", "failed")
        r2 = _record("r2", "active")
        r3 = _record("r3", "exhausted")
        r4 = _record("r4", "active")
        r5 = _record("r5", "cascade_skipped")

        context = _make_context()
        context.source_data = [r1, r2, r3, r4, r5]

        hitl_response = {
            "hitl_status": "approved",
            "record_reviews": [
                {"hitl_status": "approved", "user_comment": "R2 approved"},
                {"hitl_status": "rejected", "user_comment": "R4 rejected"},
            ],
        }

        with patch(
            "agent_actions.processing.strategies.hitl.run_dynamic_agent",
            return_value=([hitl_response], True),
        ):
            results = HITLStrategy().invoke([r1, r2, r3, r4, r5], context)

        unprocessed = [r for r in results if r.status == ProcessingStatus.UNPROCESSED]
        successes = [r for r in results if r.status == ProcessingStatus.SUCCESS]
        assert len(unprocessed) == 3  # R1, R3, R5 quarantined
        assert len(successes) == 1

        success_data = successes[0].data
        assert len(success_data) == 2  # R2 and R4 only

        r2_content = success_data[0].get("content", {}).get("hitl_review", {})
        assert r2_content.get("user_comment") == "R2 approved"

        r4_content = success_data[1].get("content", {}).get("hitl_review", {})
        assert r4_content.get("user_comment") == "R4 rejected"
