"""Tests for async reprompt path with EvaluationLoop graduated pool pattern.

These tests verify the rewritten handle_reprompt_recovery() and
check_and_submit_reprompt() functions that use EvaluationLoop.split()
to evaluate ONLY reprompt results (not the full accumulated set).
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryStateManager,
)
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.storage.backend import DISPOSITION_EXHAUSTED

# Module path prefix for patching deferred imports in processing_recovery.
_MOD = "agent_actions.llm.batch.services.processing_recovery"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(custom_id: str, content: str = "ok", success: bool = True) -> BatchResult:
    return BatchResult(custom_id=custom_id, content=content, success=success)


def _make_state(**overrides) -> MagicMock:
    """Create a mock RecoveryState with all fields including graduated pool additions."""
    defaults = {
        "phase": "reprompt",
        "retry_attempt": 0,
        "retry_max_attempts": 3,
        "missing_ids": [],
        "record_failure_counts": {},
        "reprompt_attempt": 0,
        "reprompt_max_attempts": 2,
        "validation_name": None,
        "reprompt_attempts_per_record": {},
        "validation_status": {},
        "on_exhausted": "return_last",
        "accumulated_results": [],
        "graduated_results": [],
        "evaluation_strategy_name": None,
    }
    defaults.update(overrides)
    state = MagicMock()
    for k, v in defaults.items():
        setattr(state, k, v)
    return state


def _make_service():
    """Create a mock BatchProcessingService."""
    service = MagicMock()
    service._retry_service = MagicMock(spec=BatchRetryService)
    service._retry_service.submit_reprompt_batch.return_value = ("batch-123", 2)
    service._retry_service.apply_exhausted_reprompt_metadata.side_effect = (
        lambda results, **kw: results
    )
    service._storage_backend = MagicMock()
    return service


def _make_entry(**overrides):
    defaults = dict(
        batch_id="batch-abc",
        status=BatchStatus.SUBMITTED,
        timestamp="2026-04-20T00:00:00Z",
        provider="openai",
        record_count=3,
        file_name="test_reprompt_1",
        parent_file_name="test_parent",
        recovery_type="reprompt",
        recovery_attempt=1,
    )
    defaults.update(overrides)
    return BatchJobEntry(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_validation_setup():
    """Mock validation UDF loading so tests don't need real UDF modules."""
    with (
        patch(
            "agent_actions.llm.batch.services.reprompt_ops._load_validation_udf",
        ),
        patch(
            "agent_actions.processing.recovery.validation.get_validation_function",
            return_value=(lambda x: True, "fix it"),
        ),
        patch(
            "agent_actions.processing.recovery.response_validator.resolve_feedback_strategies",
            return_value=[],
        ),
    ):
        yield


@pytest.fixture()
def mock_loop():
    """A controllable EvaluationLoop instance with patched constructor."""
    loop = MagicMock()
    loop.split.return_value = ([], [])
    loop.tag_graduated = MagicMock()
    with patch("agent_actions.processing.evaluation.EvaluationLoop", return_value=loop):
        yield loop


# ---------------------------------------------------------------------------
# handle_reprompt_recovery tests
# ---------------------------------------------------------------------------


class TestHandleRepromptRecoveryGraduatedPool:
    """Verify handle_reprompt_recovery evaluates ONLY recovery_results."""

    def _call(self, service, **kwargs):
        from agent_actions.llm.batch.services.processing_recovery import (
            handle_reprompt_recovery,
        )

        defaults = dict(
            state=_make_state(),
            recovery_results=[],
            accumulated=[],
            context_map={},
            output_directory="/tmp/test",
            parent_file_name="parent",
            entry=_make_entry(),
            agent_config={"reprompt": {"validation": "v"}},
            manager=MagicMock(),
            provider=MagicMock(),
            action_name="act",
            start_time=0.0,
        )
        defaults.update(kwargs)
        return handle_reprompt_recovery(service, **defaults)

    def test_split_called_with_only_recovery_results(self, mock_loop):
        """loop.split() receives recovery_results, NOT merged accumulated."""
        recovery = [_result("r1"), _result("r2")]
        accumulated = [_result("old1"), _result("old2"), _result("old3")]
        mock_loop.split.return_value = ([_result("r1")], [_result("r2")])

        service = _make_service()
        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
        ):
            self._call(
                service,
                recovery_results=recovery,
                accumulated=accumulated,
                state=_make_state(reprompt_attempt=0, reprompt_max_attempts=2),
            )

        mock_loop.split.assert_called_once_with(recovery)

    def test_graduated_results_grow_after_each_cycle(self, mock_loop):
        """state.graduated_results accumulates graduated records across cycles."""
        r1, r2 = _result("r1", "pass"), _result("r2", "fail")
        mock_loop.split.return_value = ([r1], [r2])

        prior_graduated = [{"custom_id": "r0", "content": "prior", "success": True}]
        state = _make_state(
            reprompt_attempt=0, reprompt_max_attempts=2, graduated_results=list(prior_graduated)
        )
        service = _make_service()

        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
        ):
            self._call(service, state=state, recovery_results=[r1, r2])

        assert len(state.graduated_results) > len(prior_graduated)

    def test_record_count_invariant(self, mock_loop):
        """Only still_failing records are submitted for reprompt."""
        recovery = [_result("r1"), _result("r2"), _result("r3")]
        mock_loop.split.return_value = ([_result("r1"), _result("r3")], [_result("r2")])

        service = _make_service()
        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
        ):
            self._call(
                service,
                recovery_results=recovery,
                state=_make_state(reprompt_attempt=0, reprompt_max_attempts=2),
            )

        service._retry_service.submit_reprompt_batch.assert_called_once()
        call_kwargs = service._retry_service.submit_reprompt_batch.call_args
        assert len(call_kwargs.kwargs["failed_results"]) == 1
        assert call_kwargs.kwargs["failed_results"][0].custom_id == "r2"

    def test_exhaustion_marks_still_failing_and_adds_to_graduated(self, mock_loop):
        """When max_attempts reached, still_failing get exhaustion metadata and join graduated."""
        r1, r2 = _result("r1", "pass"), _result("r2", "fail")
        mock_loop.split.return_value = ([r1], [r2])

        state = _make_state(reprompt_attempt=2, reprompt_max_attempts=2, graduated_results=[])
        service = _make_service()

        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
            patch.object(service, "_convert_batch_results_to_workflow_format", return_value=[]),
            patch.object(service, "_determine_output_path", return_value="/tmp/out.json"),
            patch.object(service, "_write_batch_output"),
            patch.object(service, "_cleanup_recovery_entries"),
            patch(f"{_MOD}.fire_event"),
        ):
            self._call(service, state=state, recovery_results=[r1, r2])

        service._retry_service.apply_exhausted_reprompt_metadata.assert_called_once()
        call_kwargs = service._retry_service.apply_exhausted_reprompt_metadata.call_args.kwargs
        assert call_kwargs["validation_name"] == "validation"
        assert {r.custom_id for r in call_kwargs["results"]} == {"r2"}
        # Only graduated records (r1) are in state; exhausted records (r2) are
        # combined directly at finalization without a serialize round-trip.
        assert len(state.graduated_results) == 1

    def test_all_graduated_no_submission(self, mock_loop):
        """When all recovery_results pass, no reprompt batch is submitted."""
        recovery = [_result("r1"), _result("r2")]
        mock_loop.split.return_value = (recovery, [])

        service = _make_service()
        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
            patch.object(service, "_convert_batch_results_to_workflow_format", return_value=[]),
            patch.object(service, "_determine_output_path", return_value="/tmp/out.json"),
            patch.object(service, "_write_batch_output"),
            patch.object(service, "_cleanup_recovery_entries"),
            patch(f"{_MOD}.fire_event"),
        ):
            result = self._call(
                service,
                recovery_results=recovery,
                state=_make_state(reprompt_attempt=1, reprompt_max_attempts=2),
            )

        assert result is not None
        service._retry_service.submit_reprompt_batch.assert_not_called()

    def test_submission_failure_falls_through_to_exhaustion(self, mock_loop):
        """When submit_reprompt_batch returns None under max attempts, treat as exhausted."""
        r1, r2 = _result("r1", "pass"), _result("r2", "fail")
        mock_loop.split.return_value = ([r1], [r2])

        state = _make_state(reprompt_attempt=0, reprompt_max_attempts=2, graduated_results=[])
        service = _make_service()
        service._retry_service.submit_reprompt_batch.return_value = None

        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
            patch.object(service, "_convert_batch_results_to_workflow_format", return_value=[]),
            patch.object(service, "_determine_output_path", return_value="/tmp/out.json"),
            patch.object(service, "_write_batch_output"),
            patch.object(service, "_cleanup_recovery_entries"),
            patch(f"{_MOD}.fire_event"),
        ):
            result = self._call(service, state=state, recovery_results=[r1, r2])

        assert result is not None
        service._retry_service.apply_exhausted_reprompt_metadata.assert_called_once()


# ---------------------------------------------------------------------------
# check_and_submit_reprompt tests
# ---------------------------------------------------------------------------


class TestCheckAndSubmitRepromptGraduatedPool:
    """Verify check_and_submit_reprompt uses EvaluationLoop for initial split."""

    def _call(self, service, **kwargs):
        from agent_actions.llm.batch.services.processing_recovery import (
            check_and_submit_reprompt,
        )

        defaults = dict(
            batch_results=[],
            context_map={},
            output_directory="/tmp/test",
            file_name="test_file",
            entry=_make_entry(),
            agent_config={"reprompt": {"validation": "v", "max_attempts": 2}},
            manager=MagicMock(),
            provider=MagicMock(),
        )
        defaults.update(kwargs)
        return check_and_submit_reprompt(service, **defaults)

    def test_uses_evaluation_loop_split(self, mock_loop):
        """EvaluationLoop.split() is used instead of validate_results()."""
        batch = [_result("r1"), _result("r2")]
        mock_loop.split.return_value = ([_result("r1")], [_result("r2")])

        service = _make_service()
        with patch.object(RecoveryStateManager, "save"):
            result = self._call(service, batch_results=batch)

        assert result is False
        mock_loop.split.assert_called_once_with(batch)
        service._retry_service.validate_results.assert_not_called()

    def test_all_pass_returns_true(self, mock_loop):
        """When all results pass evaluation, returns True (no reprompt needed)."""
        batch = [_result("r1"), _result("r2")]
        mock_loop.split.return_value = (batch, [])

        result = self._call(_make_service(), batch_results=batch)
        assert result is True

    def test_exhausted_returns_true_and_applies_metadata(self, mock_loop):
        """When current_attempt >= max_attempts, applies exhaustion metadata and returns True."""
        batch = [_result("r1"), _result("r2")]
        mock_loop.split.return_value = ([_result("r1")], [_result("r2")])

        service = _make_service()
        recovery_state = _make_state(reprompt_attempt=2)

        result = self._call(service, batch_results=batch, recovery_state=recovery_state)

        assert result is True
        service._retry_service.apply_exhausted_reprompt_metadata.assert_called_once()
        service._retry_service.submit_reprompt_batch.assert_not_called()

    def test_no_reprompt_config_returns_true(self):
        """When reprompt is not configured, returns True immediately."""
        result = self._call(_make_service(), agent_config={})
        assert result is True

    def test_graduated_saved_to_state(self, mock_loop):
        """Graduated results are persisted to state.graduated_results."""
        r1, r2 = _result("r1", "pass"), _result("r2", "fail")
        mock_loop.split.return_value = ([r1], [r2])

        service = _make_service()
        saved_state = {}

        def capture_save(output_dir, file_name, state):
            saved_state["graduated_results"] = state.graduated_results
            saved_state["evaluation_strategy_name"] = state.evaluation_strategy_name

        with patch.object(RecoveryStateManager, "save", side_effect=capture_save):
            self._call(service, batch_results=[r1, r2])

        assert len(saved_state["graduated_results"]) == 1
        assert saved_state["graduated_results"][0]["custom_id"] == "r1"
        assert saved_state["evaluation_strategy_name"] == "validation"


# ---------------------------------------------------------------------------
# write_record_dispositions tests
# ---------------------------------------------------------------------------


class TestWriteRecordDispositionsEvaluationExhausted:
    """Verify DISPOSITION_EXHAUSTED for evaluation-exhausted records."""

    def test_evaluation_exhausted_disposition(self):
        """Records with _recovery.reprompt.passed=False get DISPOSITION_EXHAUSTED."""
        service = _make_service()
        items = [
            {
                "source_guid": "sg-1",
                "metadata": {},
                "_recovery": {
                    "reprompt": {"attempts": 2, "passed": False, "validation": "check_schema"}
                },
            }
        ]

        from agent_actions.processing.result_collector import (
            write_record_dispositions,
        )

        write_record_dispositions(service._storage_backend, items, "my_action")
        service._storage_backend.set_disposition.assert_called_once_with(
            "my_action", "sg-1", DISPOSITION_EXHAUSTED, reason="evaluation_exhausted:check_schema"
        )

    def test_evaluation_exhausted_takes_precedence_over_retry_exhausted(self):
        """If both _recovery.reprompt.passed=False AND retry_exhausted, evaluation wins."""
        service = _make_service()
        items = [
            {
                "source_guid": "sg-1",
                "metadata": {"retry_exhausted": True},
                "_recovery": {
                    "reprompt": {"attempts": 2, "passed": False, "validation": "check_output"}
                },
            }
        ]

        from agent_actions.processing.result_collector import (
            write_record_dispositions,
        )

        write_record_dispositions(service._storage_backend, items, "my_action")
        service._storage_backend.set_disposition.assert_called_once()
        reason = service._storage_backend.set_disposition.call_args.kwargs["reason"]
        assert reason == "evaluation_exhausted:check_output"

    def test_retry_exhausted_still_works(self):
        """Existing retry_exhausted path is preserved when no reprompt recovery."""
        service = _make_service()
        items = [{"source_guid": "sg-1", "metadata": {"retry_exhausted": True}}]

        from agent_actions.processing.result_collector import (
            write_record_dispositions,
        )

        write_record_dispositions(service._storage_backend, items, "my_action")
        service._storage_backend.set_disposition.assert_called_once_with(
            "my_action", "sg-1", DISPOSITION_EXHAUSTED, reason="retry_exhausted"
        )

    def test_unknown_validation_fallback(self):
        """Missing validation name defaults to 'unknown'."""
        service = _make_service()
        items = [
            {"source_guid": "sg-1", "metadata": {}, "_recovery": {"reprompt": {"passed": False}}}
        ]

        from agent_actions.processing.result_collector import (
            write_record_dispositions,
        )

        write_record_dispositions(service._storage_backend, items, "my_action")
        reason = service._storage_backend.set_disposition.call_args.kwargs["reason"]
        assert reason == "evaluation_exhausted:unknown"

    def test_passed_true_not_treated_as_exhausted(self):
        """Records with _recovery.reprompt.passed=True are NOT exhausted."""
        service = _make_service()
        items = [
            {
                "source_guid": "sg-1",
                "metadata": {},
                "_recovery": {"reprompt": {"attempts": 1, "passed": True, "validation": "v"}},
            }
        ]

        from agent_actions.processing.result_collector import (
            write_record_dispositions,
        )

        write_record_dispositions(service._storage_backend, items, "my_action")
        service._storage_backend.set_disposition.assert_not_called()
