"""Tests for composed exhaustion and phase transitions — must pass pre-refactor.

These tests verify:
- Retry→reprompt composed recovery paths (5 scenarios)
- Phase transition mechanics (retry exhaustion → reprompt)
- RecoveryState serialization roundtrip with all fields
- Graduated pool monotonicity across phases

All tests pass against unmodified source code.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
)
from agent_actions.llm.batch.services.processing_recovery import (
    handle_reprompt_recovery,
    handle_retry_recovery,
)
from agent_actions.llm.providers.batch_base import BatchResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(custom_id: str, success: bool = True) -> BatchResult:
    return BatchResult(custom_id=custom_id, content=f"content-{custom_id}", success=success)


def _make_entry(recovery_type: str = "retry") -> BatchJobEntry:
    return BatchJobEntry(
        batch_id="batch-123",
        status=BatchStatus.SUBMITTED,
        timestamp="2026-05-01T00:00:00Z",
        provider="openai",
        record_count=3,
        file_name="test_file_retry_1",
        parent_file_name="test_file",
        recovery_type=recovery_type,
        recovery_attempt=1,
    )


def _make_state(**kwargs) -> RecoveryState:
    defaults = {
        "phase": "retry",
        "retry_attempt": 3,
        "retry_max_attempts": 3,
        "missing_ids": ["id-missing"],
        "record_failure_counts": {"id-missing": 3},
        "reprompt_attempt": 0,
        "reprompt_max_attempts": 2,
        "on_exhausted": "return_last",
        "accumulated_results": [],
        "graduated_results": [],
    }
    defaults.update(kwargs)
    return RecoveryState(**defaults)


def _mock_service():
    service = MagicMock()
    service._retry_service = MagicMock()
    service._storage_backend = MagicMock()
    service._action_name = "test_action"
    service._convert_batch_results_to_workflow_format = MagicMock(return_value=[])
    service._determine_output_path = MagicMock(return_value="/tmp/output.json")
    service._write_batch_output = MagicMock()
    service._cleanup_recovery_entries = MagicMock()
    service._update_prompt_trace_responses = MagicMock()
    return service


# ---------------------------------------------------------------------------
# TestComposedRecoveryPaths
# ---------------------------------------------------------------------------


class TestComposedRecoveryPaths:
    """End-to-end composed recovery scenarios."""

    @patch("agent_actions.llm.batch.services.processing_recovery.fire_event")
    @patch("agent_actions.llm.batch.services.processing_recovery.write_record_dispositions")
    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_retry_exhausted_then_reprompt_succeeds(self, mock_mgr, mock_build_loop, _disp, _event):
        """Happy composed: retry exhausts, reprompt evaluates all as passing → finalize."""
        service = _mock_service()
        state = _make_state(retry_attempt=3, retry_max_attempts=3)

        # Retry: still missing after max attempts
        service._retry_service.process_retry_results.return_value = (
            [_make_result("id-1")],
            {"id-missing"},
            {"id-missing": 3},
            [],
        )
        service._retry_service.build_exhausted_recovery.return_value = {"id-missing": MagicMock()}

        # Reprompt: all pass evaluation (no failures)
        loop = MagicMock()
        strategy = MagicMock()
        strategy.name = "schema_check"
        strategy.max_attempts = 2
        strategy.on_exhausted = "return_last"
        loop.split.return_value = ([_make_result("id-1")], [])
        mock_build_loop.return_value = (loop, strategy, None)

        result = handle_retry_recovery(
            service,
            state=state,
            recovery_results=[_make_result("id-1")],
            accumulated=[],
            context_map={},
            output_directory="/tmp",
            parent_file_name="test_file",
            entry=_make_entry(),
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            action_name="test_action",
            start_time=0.0,
        )

        # Composed path completed: output written
        assert result == "/tmp/output.json"
        service._write_batch_output.assert_called_once()

    @patch("agent_actions.llm.batch.services.processing_recovery.fire_event")
    @patch("agent_actions.llm.batch.services.processing_recovery.write_record_dispositions")
    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_retry_exhausted_then_reprompt_exhausted_return_last(
        self, mock_mgr, mock_build_loop, _disp, _event
    ):
        """Both exhausted, graceful: reprompt exhausted with return_last → finalize with metadata."""
        service = _mock_service()
        state = _make_state(retry_attempt=3, retry_max_attempts=3)

        service._retry_service.process_retry_results.return_value = (
            [_make_result("id-1")],
            {"id-missing"},
            {"id-missing": 3},
            [],
        )
        service._retry_service.build_exhausted_recovery.return_value = {"id-missing": MagicMock()}

        # Reprompt: some failing, but already at max attempts → exhausted
        loop = MagicMock()
        strategy = MagicMock()
        strategy.name = "schema_check"
        strategy.max_attempts = 0  # Already at max (current_attempt >= max)
        strategy.on_exhausted = "return_last"
        failing_result = _make_result("id-1", success=False)
        loop.split.return_value = ([], [failing_result])
        mock_build_loop.return_value = (loop, strategy, None)

        result = handle_retry_recovery(
            service,
            state=state,
            recovery_results=[_make_result("id-1")],
            accumulated=[],
            context_map={},
            output_directory="/tmp",
            parent_file_name="test_file",
            entry=_make_entry(),
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            action_name="test_action",
            start_time=0.0,
        )

        # Exhaustion metadata applied (return_last path — no raise)
        assert result == "/tmp/output.json"
        service._retry_service.apply_exhausted_reprompt_metadata.assert_called_once()
        call_kwargs = service._retry_service.apply_exhausted_reprompt_metadata.call_args[1]
        assert call_kwargs["on_exhausted"] == "return_last"

    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_retry_exhausted_then_reprompt_exhausted_raise(self, mock_mgr, mock_build_loop):
        """Both exhausted, raises: on_exhausted='raise' propagates RuntimeError."""
        service = _mock_service()
        state = _make_state(retry_attempt=3, retry_max_attempts=3)

        service._retry_service.process_retry_results.return_value = (
            [_make_result("id-1")],
            {"id-missing"},
            {"id-missing": 3},
            [],
        )
        service._retry_service.build_exhausted_recovery.return_value = {"id-missing": MagicMock()}

        # Reprompt: failing + exhausted + raise policy
        loop = MagicMock()
        strategy = MagicMock()
        strategy.name = "schema_check"
        strategy.max_attempts = 0
        strategy.on_exhausted = "raise"
        failing_result = _make_result("id-1", success=False)
        loop.split.return_value = ([], [failing_result])
        mock_build_loop.return_value = (loop, strategy, None)

        # Wire the real exhaustion function to get the raise
        from agent_actions.processing.evaluation.exhaustion import apply_exhausted_reprompt

        service._retry_service.apply_exhausted_reprompt_metadata.side_effect = (
            lambda **kwargs: apply_exhausted_reprompt(**kwargs)
        )

        with pytest.raises(RuntimeError, match="Reprompt validation exhausted"):
            handle_retry_recovery(
                service,
                state=state,
                recovery_results=[_make_result("id-1")],
                accumulated=[],
                context_map={},
                output_directory="/tmp",
                parent_file_name="test_file",
                entry=_make_entry(),
                agent_config={"kind": "llm"},
                manager=MagicMock(),
                provider=MagicMock(),
                action_name="test_action",
                start_time=0.0,
            )

    @patch("agent_actions.llm.batch.services.processing_recovery.fire_event")
    @patch("agent_actions.llm.batch.services.processing_recovery.write_record_dispositions")
    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_retry_exhausted_no_reprompt_configured(self, mock_mgr, mock_build_loop, _disp, _event):
        """Retry-only exhaustion: no reprompt configured → finalize with exhaustion metadata."""
        service = _mock_service()
        state = _make_state(retry_attempt=3, retry_max_attempts=3)

        service._retry_service.process_retry_results.return_value = (
            [_make_result("id-1")],
            {"id-missing"},
            {"id-missing": 3},
            [],
        )
        service._retry_service.build_exhausted_recovery.return_value = {"id-missing": MagicMock()}
        # No reprompt configured
        mock_build_loop.return_value = None

        result = handle_retry_recovery(
            service,
            state=state,
            recovery_results=[_make_result("id-1")],
            accumulated=[],
            context_map={},
            output_directory="/tmp",
            parent_file_name="test_file",
            entry=_make_entry(),
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            action_name="test_action",
            start_time=0.0,
        )

        # Finalizes directly without reprompt
        assert result == "/tmp/output.json"
        # No reprompt metadata applied
        service._retry_service.apply_exhausted_reprompt_metadata.assert_not_called()
        # State cleaned up
        mock_mgr.delete.assert_called_once()

    @patch("agent_actions.llm.batch.services.processing_recovery.fire_event")
    @patch("agent_actions.llm.batch.services.processing_recovery.write_record_dispositions")
    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_reprompt_only_all_graduated(self, mock_mgr, mock_build_loop, _disp, _event):
        """Reprompt-only: no retry needed, all pass evaluation → finalize."""
        service = _mock_service()
        state = _make_state(phase="reprompt", retry_attempt=0, missing_ids=[])

        loop = MagicMock()
        strategy = MagicMock()
        strategy.name = "validation"
        loop.split.return_value = ([_make_result("id-1"), _make_result("id-2")], [])
        mock_build_loop.return_value = (loop, strategy, None)

        result = handle_reprompt_recovery(
            service,
            state=state,
            recovery_results=[_make_result("id-1"), _make_result("id-2")],
            accumulated=[],
            context_map={},
            output_directory="/tmp",
            parent_file_name="test_file",
            entry=_make_entry(recovery_type="reprompt"),
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            action_name="test_action",
            start_time=0.0,
        )

        assert result == "/tmp/output.json"
        mock_mgr.delete.assert_called_once()


# ---------------------------------------------------------------------------
# TestRecoveryStateRoundtrip
# ---------------------------------------------------------------------------


class TestRecoveryStateRoundtrip:
    """RecoveryState serialization with all fields populated."""

    def test_full_state_serialize_deserialize(self):
        """All fields roundtrip: graduated_results + retry + reprompt counts."""
        state = RecoveryState(
            phase="reprompt",
            retry_attempt=3,
            retry_max_attempts=3,
            missing_ids=["id-42", "id-99"],
            record_failure_counts={"id-42": 3, "id-99": 2},
            reprompt_attempt=2,
            reprompt_max_attempts=3,
            validation_name="schema_check",
            reprompt_attempts_per_record={"id-1": 2, "id-2": 1},
            validation_status={"id-1": False, "id-2": True},
            on_exhausted="raise",
            accumulated_results=[{"custom_id": "id-1", "content": "data", "success": True}],
            graduated_results=[{"custom_id": "id-2", "content": "good", "success": True}],
            evaluation_strategy_name="validation",
        )

        serialized = state.to_dict()
        restored = RecoveryState(**serialized)

        assert restored.phase == "reprompt"
        assert restored.retry_attempt == 3
        assert restored.retry_max_attempts == 3
        assert restored.missing_ids == ["id-42", "id-99"]
        assert restored.record_failure_counts == {"id-42": 3, "id-99": 2}
        assert restored.reprompt_attempt == 2
        assert restored.reprompt_max_attempts == 3
        assert restored.validation_name == "schema_check"
        assert restored.reprompt_attempts_per_record == {"id-1": 2, "id-2": 1}
        assert restored.validation_status == {"id-1": False, "id-2": True}
        assert restored.on_exhausted == "raise"
        assert len(restored.accumulated_results) == 1
        assert restored.accumulated_results[0]["custom_id"] == "id-1"
        assert len(restored.graduated_results) == 1
        assert restored.graduated_results[0]["custom_id"] == "id-2"
        assert restored.evaluation_strategy_name == "validation"

    def test_minimal_state_deserializes_with_defaults(self):
        """Only required field (phase) → all optional fields get defaults."""
        state = RecoveryState(phase="retry")
        serialized = state.to_dict()
        restored = RecoveryState(**serialized)

        assert restored.phase == "retry"
        assert restored.retry_attempt == 0
        assert restored.missing_ids == []
        assert restored.graduated_results == []
        assert restored.on_exhausted == "return_last"
        assert restored.evaluation_strategy_name is None

    def test_invalid_phase_raises(self):
        """Invalid phase value raises ValueError."""
        with pytest.raises(ValueError, match="Invalid recovery phase"):
            RecoveryState(phase="invalid")


# ---------------------------------------------------------------------------
# TestGraduatedPoolMonotonicity
# ---------------------------------------------------------------------------


class TestGraduatedPoolMonotonicity:
    """Graduated records never re-evaluated across recovery phases."""

    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_only_recovery_results_passed_to_split(self, mock_mgr, mock_build_loop):
        """handle_reprompt_recovery passes only recovery_results to loop.split, not graduated."""
        loop = MagicMock()
        strategy = MagicMock()
        strategy.name = "validation"

        # Split returns: id-new graduated, id-still-bad failing
        loop.split.return_value = ([_make_result("id-new")], [_make_result("id-still-bad")])
        mock_build_loop.return_value = (loop, strategy, None)

        service = _mock_service()
        state = _make_state(
            phase="reprompt",
            reprompt_attempt=1,
            reprompt_max_attempts=3,
            # Prior graduated results — these must NOT be passed to split()
            graduated_results=[{"custom_id": "id-prior-grad", "content": "old", "success": True}],
        )
        service._retry_service.submit_reprompt_batch.return_value = ("batch-2", 1)

        recovery_results = [_make_result("id-new"), _make_result("id-still-bad")]

        handle_reprompt_recovery(
            service,
            state=state,
            recovery_results=recovery_results,
            accumulated=[],
            context_map={},
            output_directory="/tmp",
            parent_file_name="test_file",
            entry=_make_entry(recovery_type="reprompt"),
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            action_name="test_action",
            start_time=0.0,
        )

        # Key invariant: split() received ONLY recovery_results, not prior graduated
        split_args = loop.split.call_args[0]
        split_input = split_args[0]
        split_ids = {r.custom_id for r in split_input}
        assert "id-prior-grad" not in split_ids
        assert split_ids == {"id-new", "id-still-bad"}

    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_graduated_pool_grows_monotonically(self, mock_mgr, mock_build_loop):
        """Each reprompt cycle adds to graduated — never removes prior graduates."""
        loop = MagicMock()
        strategy = MagicMock()
        strategy.name = "validation"
        # This cycle: id-2 graduates, id-3 still fails
        loop.split.return_value = ([_make_result("id-2")], [_make_result("id-3")])
        mock_build_loop.return_value = (loop, strategy, None)

        service = _mock_service()
        service._retry_service.submit_reprompt_batch.return_value = ("batch-next", 1)

        # State: cycle 1 already graduated id-1
        state = _make_state(
            phase="reprompt",
            reprompt_attempt=1,
            reprompt_max_attempts=3,
            graduated_results=[{"custom_id": "id-1", "content": "c1", "success": True}],
        )

        handle_reprompt_recovery(
            service,
            state=state,
            recovery_results=[_make_result("id-2"), _make_result("id-3")],
            accumulated=[],
            context_map={},
            output_directory="/tmp",
            parent_file_name="test_file",
            entry=_make_entry(recovery_type="reprompt"),
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            action_name="test_action",
            start_time=0.0,
        )

        # Monotonicity: prior graduate preserved + new one appended
        assert len(state.graduated_results) == 2
        grad_ids = {r["custom_id"] for r in state.graduated_results}
        assert grad_ids == {"id-1", "id-2"}
