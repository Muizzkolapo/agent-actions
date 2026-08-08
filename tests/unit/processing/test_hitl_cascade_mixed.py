"""Test HITL cascade filtering through UnifiedProcessor.

Proves that when cascade-blocked records are present in input,
UnifiedProcessor filters them before the strategy sees them, and
HITL review decisions are applied to the correct active records
by position (not misattributed to quarantined records).

After the cascade-filter-enforcement refactor, cascade filtering
happens in UnifiedProcessor.process(), not inside each strategy.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.processing.disposition_gate import DispositionGate
from agent_actions.processing.strategies.hitl import HITLStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.processing.unified import UnifiedProcessor
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


class _SpyStrategy:
    """Test strategy that records received records and returns success for each."""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []

    def invoke(
        self,
        records: list[dict[str, Any]],
        context: ProcessingContext,
    ) -> list[ProcessingResult]:
        self.received.extend(records)
        return [
            ProcessingResult.success(data=[r], source_guid=r.get("source_guid")) for r in records
        ]


class TestHITLCascadeMixed:
    """HITL with mixed active + cascade-blocked records via UnifiedProcessor."""

    def test_reviews_applied_to_correct_records(self):
        """Input: [R1 active, R2 failed, R3 active].
        HITL sees [R1, R3] (processable only).
        Returns record_reviews for [R1, R3].
        R1 gets review_for_R1, R3 gets review_for_R3.
        R2 appears as a quarantined tombstone in output.
        """
        r1 = _record("r1", "active")
        r2 = _record("r2", "failed")
        r3 = _record("r3", "active")

        context = _make_context()
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
            processor = UnifiedProcessor()
            strategy = HITLStrategy()
            # FILE mode: pass raw_records to trigger FILE-mode guard path
            output, stats = processor.process(
                [r1, r2, r3], context, strategy, raw_records=[r1, r2, r3]
            )

        # R2 should appear as unprocessed in output
        r2_out = [r for r in output if r.get("source_guid") == "r2"]
        assert len(r2_out) == 1

        # R1 and R3 should have HITL review data
        r1_out = [r for r in output if r.get("source_guid") == "r1"]
        r3_out = [r for r in output if r.get("source_guid") == "r3"]
        assert len(r1_out) == 1
        assert len(r3_out) == 1

        r1_content = r1_out[0].get("content", {})
        hitl_ns = r1_content.get("hitl_review", {})
        assert hitl_ns.get("user_comment") == "R1 looks good"

        r3_content = r3_out[0].get("content", {})
        hitl_ns_r3 = r3_content.get("hitl_review", {})
        assert hitl_ns_r3.get("user_comment") == "R3 needs work"

    def test_all_quarantined_returns_only_tombstones(self):
        """When all records are cascade-blocked, no HITL invocation happens."""
        r1 = _record("r1", "failed")
        r2 = _record("r2", "exhausted")

        context = _make_context()
        context.source_data = [r1, r2]

        # run_dynamic_agent should NOT be called — all quarantined
        with patch(
            "agent_actions.processing.strategies.hitl.run_dynamic_agent",
        ) as mock_agent:
            processor = UnifiedProcessor()
            strategy = HITLStrategy()
            output, stats = processor.process([r1, r2], context, strategy, raw_records=[r1, r2])

        mock_agent.assert_not_called()
        assert stats.unprocessed == 2

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
            processor = UnifiedProcessor()
            strategy = HITLStrategy()
            output, stats = processor.process(
                [r1, r2, r3, r4, r5], context, strategy, raw_records=[r1, r2, r3, r4, r5]
            )

        # R1, R3, R5 quarantined
        assert stats.unprocessed == 3

        # R2 and R4 should have correct reviews
        r2_out = next(r for r in output if r.get("source_guid") == "r2")
        r4_out = next(r for r in output if r.get("source_guid") == "r4")

        r2_content = r2_out.get("content", {}).get("hitl_review", {})
        assert r2_content.get("user_comment") == "R2 approved"

        r4_content = r4_out.get("content", {}).get("hitl_review", {})
        assert r4_content.get("user_comment") == "R4 rejected"


class TestStrategyReceivesOnlyProcessable:
    """Verify strategies never see cascade-blocked records."""

    def test_cascade_blocked_never_reach_strategy(self):
        """Mock strategy records what it receives. Assert no cascade-blocked records."""
        r1 = _record("r1", "active")
        r2 = _record("r2", "failed")
        r3 = _record("r3", "cascade_skipped")
        r4 = _record("r4", "active")

        spy = _SpyStrategy()
        context = _make_context()
        processor = UnifiedProcessor()
        output, stats = processor.process([r1, r2, r3, r4], context, spy)

        # Strategy should only see R1 and R4
        assert len(spy.received) == 2
        guids = {r.get("source_guid") for r in spy.received}
        assert guids == {"r1", "r4"}

        # R2 and R3 should appear as unprocessed in output
        assert stats.unprocessed == 2

    def test_new_strategy_without_cascade_call_still_works(self):
        """A bare ProcessingStrategy with no cascade logic still works —
        UnifiedProcessor handles cascade filtering."""

        class BareStrategy:
            def invoke(
                self,
                records: list[dict[str, Any]],
                context: ProcessingContext,
            ) -> list[ProcessingResult]:
                return [
                    ProcessingResult.success(data=[r], source_guid=r.get("source_guid"))
                    for r in records
                ]

        r1 = _record("r1", "active")
        r2 = _record("r2", "failed")

        context = _make_context()
        processor = UnifiedProcessor()
        output, stats = processor.process([r1, r2], context, BareStrategy())

        assert stats.success == 1
        assert stats.unprocessed == 1


class TestGateCascadeInteraction:
    """Verify disposition gate + cascade filter interact correctly.

    Gate runs first (carries forward already-terminal records), then
    cascade filter quarantines upstream-failed records. Both reduce
    what the strategy sees.
    """

    def test_gate_carry_forward_plus_cascade_quarantine(self):
        """R1 active (process), R2 failed (cascade), R3 active but terminal (gate).

        Strategy should only see R1. R2 quarantined by cascade filter.
        R3 carried forward by disposition gate.
        """
        r1 = _record("r1", "active")
        r2 = _record("r2", "failed")
        r3 = _record("r3", "active")

        # Mock storage backend: R3 has terminal disposition
        mock_backend = MagicMock()
        mock_backend.get_terminal_record_ids.return_value = {"r3"}
        mock_backend.read_target.return_value = [
            {"source_guid": "r3", "content": {"hitl_review": {"prior": True}}}
        ]

        gate = DispositionGate(storage_backend=mock_backend)
        context = _make_context()
        context.storage_backend = mock_backend
        context.file_path = "test.json"

        spy = _SpyStrategy()
        processor = UnifiedProcessor(disposition_gate=gate)
        output, stats = processor.process([r1, r2, r3], context, spy)

        # Strategy should only see R1 (R2 cascade-quarantined, R3 gate-carried)
        assert len(spy.received) == 1
        assert spy.received[0].get("source_guid") == "r1"

        assert stats.unprocessed == 1


class TestHITLCarryForwardAlignment:
    """FILE-mode HITL reviews must stay aligned when the gate carries records.

    UnifiedProcessor re-filters ``context.source_data`` for cascade-quarantined
    records so HITL's positional broadcast stays aligned, but not for records
    the disposition gate carries forward — the sibling case, one block earlier.
    """

    def test_reviews_not_misattributed_when_gate_carries_a_record(self):
        """R1 already reviewed on a prior run; R2 and R3 are new.

        HITL is shown [R2, R3] and returns reviews in that order. Each review
        must land on the record the reviewer saw it against.
        """
        r1 = _record("r1", "active")
        r2 = _record("r2", "active")
        r3 = _record("r3", "active")

        mock_backend = MagicMock()
        mock_backend.get_terminal_record_ids.return_value = {"r1"}
        mock_backend.read_target.return_value = [
            {
                "source_guid": "r1",
                "content": {"hitl_review": {"hitl_status": "approved", "user_comment": "prior"}},
            }
        ]

        context = _make_context()
        context.source_data = [r1, r2, r3]
        context.storage_backend = mock_backend
        context.file_path = "test.json"

        hitl_response = {
            "hitl_status": "approved",
            "record_reviews": [
                {"hitl_status": "approved", "user_comment": "R2 looks good"},
                {"hitl_status": "rejected", "user_comment": "R3 needs work"},
            ],
        }

        with patch(
            "agent_actions.processing.strategies.hitl.run_dynamic_agent",
            return_value=([hitl_response], True),
        ):
            processor = UnifiedProcessor(disposition_gate=DispositionGate(mock_backend))
            output, _stats = processor.process(
                [r1, r2, r3], context, HITLStrategy(), raw_records=[r1, r2, r3]
            )

        r2_out = [r for r in output if r.get("source_guid") == "r2"]
        r3_out = [r for r in output if r.get("source_guid") == "r3"]
        assert len(r2_out) == 1
        assert len(r3_out) == 1
        assert r2_out[0]["content"]["hitl_review"]["user_comment"] == "R2 looks good"
        assert r3_out[0]["content"]["hitl_review"]["user_comment"] == "R3 needs work"

        # The carried record must appear exactly once, from prior output only.
        r1_out = [r for r in output if r.get("source_guid") == "r1"]
        assert len(r1_out) == 1
        assert r1_out[0]["content"]["hitl_review"]["user_comment"] == "prior"

    def test_reviews_stay_aligned_when_a_terminal_record_is_missing_from_prior_output(self):
        """R1 and R3 are terminal, but prior output holds only R3.

        R1 cannot be carried, so it is re-queued for processing — appended at the
        END of the work list while it still sits FIRST in source_data. Reviews
        must follow the records the reviewer saw, not the stale ordering.
        """
        r1 = _record("r1", "active")
        r2 = _record("r2", "active")
        r3 = _record("r3", "active")
        r4 = _record("r4", "active")

        mock_backend = MagicMock()
        mock_backend.get_terminal_record_ids.return_value = {"r1", "r3"}
        mock_backend.read_target.return_value = [
            {
                "source_guid": "r3",
                "content": {"hitl_review": {"hitl_status": "approved", "user_comment": "prior"}},
            }
        ]

        context = _make_context()
        context.source_data = [r1, r2, r3, r4]
        context.storage_backend = mock_backend
        context.file_path = "test.json"

        captured: dict[str, list] = {}

        def _capture(**kwargs):
            # The reviewer sees observe-filtered records; `val` carries the
            # record identity that source_guid is stripped of.
            captured["records"] = list(kwargs.get("context") or [])
            reviews = [
                {"hitl_status": "approved", "user_comment": f"review for {r.get('val')}"}
                for r in captured["records"]
            ]
            return ([{"hitl_status": "approved", "record_reviews": reviews}], True)

        with patch(
            "agent_actions.processing.strategies.hitl.run_dynamic_agent",
            side_effect=_capture,
        ):
            processor = UnifiedProcessor(disposition_gate=DispositionGate(mock_backend))
            output, _stats = processor.process(
                [r1, r2, r3, r4], context, HITLStrategy(), raw_records=[r1, r2, r3, r4]
            )

        for guid in ("r1", "r2", "r4"):
            out = [r for r in output if r.get("source_guid") == guid]
            assert len(out) == 1, f"{guid} must appear exactly once"
            assert out[0]["content"]["hitl_review"]["user_comment"] == f"review for {guid}"
