"""Tests for async reprompt path with EvaluationLoop graduated pool pattern.

These tests verify the rewritten handle_reprompt_recovery() and
check_and_submit_reprompt() functions that use EvaluationLoop.split()
to evaluate ONLY reprompt results (not the full accumulated set).

Dependencies (mocked — created by other specs):
  - EvaluationLoop (spec 062)
  - ValidationStrategy (spec 063)
  - RecoveryState.graduated_results (spec 064)
"""

import sys
from types import ModuleType
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

# ---------------------------------------------------------------------------
# Mock evaluation modules (specs 062/063 — don't exist yet in this clone)
# ---------------------------------------------------------------------------


def _make_mock_evaluation_modules():
    """Create mock modules for agent_actions.processing.evaluation."""
    eval_module = ModuleType("agent_actions.processing.evaluation")
    strategies_module = ModuleType("agent_actions.processing.evaluation.strategies")

    # Callable mocks — calling EvaluationLoop(strategy) returns .return_value
    eval_module.EvaluationLoop = MagicMock()
    strategies_module.ValidationStrategy = MagicMock()

    return eval_module, strategies_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(custom_id: str, content: str = "ok", success: bool = True) -> BatchResult:
    return BatchResult(custom_id=custom_id, content=content, success=success)


def _make_state(**overrides) -> MagicMock:
    """Create a mock RecoveryState with graduated_results + evaluation_strategy_name.

    Real RecoveryState (spec 064) will have these fields.  We use a mock
    here because the fields don't exist on this clone's RecoveryState yet.
    """
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
        # Spec 064 additions:
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
def _mock_evaluation_imports():
    """Inject mock evaluation modules so deferred imports resolve."""
    eval_mod, strat_mod = _make_mock_evaluation_modules()
    with patch.dict(
        sys.modules,
        {
            "agent_actions.processing.evaluation": eval_mod,
            "agent_actions.processing.evaluation.strategies": strat_mod,
        },
    ):
        yield eval_mod, strat_mod


@pytest.fixture()
def mock_loop():
    """A controllable EvaluationLoop instance."""
    loop = MagicMock()
    loop.split.return_value = ([], [])  # default: nothing graduates, nothing fails
    loop.tag_graduated = MagicMock()
    return loop


@pytest.fixture()
def mock_strategy():
    """A controllable ValidationStrategy instance."""
    strategy = MagicMock()
    strategy.name = "test_validation"
    strategy.max_attempts = 2
    strategy.on_exhausted = "return_last"
    return strategy


# ---------------------------------------------------------------------------
# handle_reprompt_recovery tests
# ---------------------------------------------------------------------------


class TestHandleRepromptRecoveryGraduatedPool:
    """Verify handle_reprompt_recovery evaluates ONLY recovery_results."""

    def test_split_called_with_only_recovery_results(
        self, _mock_evaluation_imports, mock_loop, mock_strategy
    ):
        """loop.split() receives recovery_results, NOT merged accumulated."""
        eval_mod, strat_mod = _mock_evaluation_imports
        strat_mod.ValidationStrategy.return_value = mock_strategy
        eval_mod.EvaluationLoop.return_value = mock_loop

        recovery = [_result("r1"), _result("r2")]
        accumulated = [_result("old1"), _result("old2"), _result("old3")]
        graduated_from_split = [_result("r1")]
        still_failing = [_result("r2")]
        mock_loop.split.return_value = (graduated_from_split, still_failing)

        state = _make_state(reprompt_attempt=0, reprompt_max_attempts=2)
        service = _make_service()
        entry = _make_entry()
        manager = MagicMock()

        from agent_actions.llm.batch.services.processing_recovery import (
            handle_reprompt_recovery,
        )

        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
        ):
            handle_reprompt_recovery(
                service,
                state=state,
                recovery_results=recovery,
                accumulated=accumulated,
                context_map={},
                output_directory="/tmp/test",
                parent_file_name="parent",
                entry=entry,
                agent_config={"reprompt": {"validation": "v"}},
                manager=manager,
                provider=MagicMock(),
                action_name="act",
                start_time=0.0,
            )

        # THE critical assertion: split was called with recovery_results only
        mock_loop.split.assert_called_once_with(recovery)

    def test_graduated_results_grow_after_each_cycle(
        self, _mock_evaluation_imports, mock_loop, mock_strategy
    ):
        """state.graduated_results accumulates graduated records across cycles."""
        eval_mod, strat_mod = _mock_evaluation_imports
        strat_mod.ValidationStrategy.return_value = mock_strategy
        eval_mod.EvaluationLoop.return_value = mock_loop

        r1, r2 = _result("r1", "pass"), _result("r2", "fail")
        mock_loop.split.return_value = ([r1], [r2])

        # Pre-existing graduated from a previous cycle
        prior_graduated = [{"custom_id": "r0", "content": "prior", "success": True}]
        state = _make_state(
            reprompt_attempt=0,
            reprompt_max_attempts=2,
            graduated_results=list(prior_graduated),
        )
        service = _make_service()

        from agent_actions.llm.batch.services.processing_recovery import (
            handle_reprompt_recovery,
        )

        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
        ):
            handle_reprompt_recovery(
                service,
                state=state,
                recovery_results=[r1, r2],
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

        # graduated_results should now contain prior + newly graduated r1
        assert len(state.graduated_results) > len(prior_graduated)

    def test_record_count_invariant(self, _mock_evaluation_imports, mock_loop, mock_strategy):
        """graduated + still_failing == len(recovery_results) on each split."""
        eval_mod, strat_mod = _mock_evaluation_imports
        strat_mod.ValidationStrategy.return_value = mock_strategy
        eval_mod.EvaluationLoop.return_value = mock_loop

        recovery = [_result("r1"), _result("r2"), _result("r3")]
        grad = [_result("r1"), _result("r3")]
        fail = [_result("r2")]
        mock_loop.split.return_value = (grad, fail)

        state = _make_state(reprompt_attempt=0, reprompt_max_attempts=2)
        service = _make_service()

        from agent_actions.llm.batch.services.processing_recovery import (
            handle_reprompt_recovery,
        )

        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
        ):
            handle_reprompt_recovery(
                service,
                state=state,
                recovery_results=recovery,
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

        # Submission was for still_failing only
        service._retry_service.submit_reprompt_batch.assert_called_once()
        call_kwargs = service._retry_service.submit_reprompt_batch.call_args
        assert len(call_kwargs.kwargs["failed_results"]) == 1
        assert call_kwargs.kwargs["failed_results"][0].custom_id == "r2"

    def test_exhaustion_marks_still_failing_and_adds_to_graduated(
        self, _mock_evaluation_imports, mock_loop, mock_strategy
    ):
        """When max_attempts reached, still_failing get exhaustion metadata and join graduated."""
        eval_mod, strat_mod = _mock_evaluation_imports
        strat_mod.ValidationStrategy.return_value = mock_strategy
        eval_mod.EvaluationLoop.return_value = mock_loop

        r1 = _result("r1", "pass")
        r2 = _result("r2", "fail")
        mock_loop.split.return_value = ([r1], [r2])

        state = _make_state(
            reprompt_attempt=2,
            reprompt_max_attempts=2,
            graduated_results=[],
        )
        service = _make_service()

        from agent_actions.llm.batch.services.processing_recovery import (
            handle_reprompt_recovery,
        )

        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
            patch.object(service, "_convert_batch_results_to_workflow_format", return_value=[]),
            patch.object(service, "_determine_output_path", return_value="/tmp/out.json"),
            patch.object(service, "_write_batch_output"),
            patch.object(service, "_cleanup_recovery_entries"),
            patch("agent_actions.llm.batch.services.processing_recovery.fire_event"),
        ):
            handle_reprompt_recovery(
                service,
                state=state,
                recovery_results=[r1, r2],
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

        # apply_exhausted_reprompt_metadata called for still_failing
        service._retry_service.apply_exhausted_reprompt_metadata.assert_called_once()
        call_kwargs = service._retry_service.apply_exhausted_reprompt_metadata.call_args.kwargs
        assert call_kwargs["validation_name"] == "test_validation"
        assert {r.custom_id for r in call_kwargs["results"]} == {"r2"}

        # Both graduated and exhausted ended up in state.graduated_results
        # (serialized r1 from graduation + serialized r2 from exhaustion)
        assert len(state.graduated_results) == 2

    def test_all_graduated_no_submission(self, _mock_evaluation_imports, mock_loop, mock_strategy):
        """When all recovery_results pass, no reprompt batch is submitted."""
        eval_mod, strat_mod = _mock_evaluation_imports
        strat_mod.ValidationStrategy.return_value = mock_strategy
        eval_mod.EvaluationLoop.return_value = mock_loop

        recovery = [_result("r1"), _result("r2")]
        mock_loop.split.return_value = (recovery, [])  # all graduate

        state = _make_state(reprompt_attempt=1, reprompt_max_attempts=2)
        service = _make_service()

        from agent_actions.llm.batch.services.processing_recovery import (
            handle_reprompt_recovery,
        )

        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
            patch.object(service, "_convert_batch_results_to_workflow_format", return_value=[]),
            patch.object(service, "_determine_output_path", return_value="/tmp/out.json"),
            patch.object(service, "_write_batch_output"),
            patch.object(service, "_cleanup_recovery_entries"),
            patch("agent_actions.llm.batch.services.processing_recovery.fire_event"),
        ):
            result = handle_reprompt_recovery(
                service,
                state=state,
                recovery_results=recovery,
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

        # Should finalize (return output path), not submit more reprompts
        assert result is not None
        service._retry_service.submit_reprompt_batch.assert_not_called()

    def test_submission_failure_falls_through_to_exhaustion(
        self, _mock_evaluation_imports, mock_loop, mock_strategy
    ):
        """When submit_reprompt_batch returns None under max attempts, treat as exhausted."""
        eval_mod, strat_mod = _mock_evaluation_imports
        strat_mod.ValidationStrategy.return_value = mock_strategy
        eval_mod.EvaluationLoop.return_value = mock_loop

        r1 = _result("r1", "pass")
        r2 = _result("r2", "fail")
        mock_loop.split.return_value = ([r1], [r2])

        state = _make_state(reprompt_attempt=0, reprompt_max_attempts=2, graduated_results=[])
        service = _make_service()
        service._retry_service.submit_reprompt_batch.return_value = None  # submission fails

        from agent_actions.llm.batch.services.processing_recovery import (
            handle_reprompt_recovery,
        )

        with (
            patch.object(RecoveryStateManager, "save"),
            patch.object(RecoveryStateManager, "delete"),
            patch.object(service, "_convert_batch_results_to_workflow_format", return_value=[]),
            patch.object(service, "_determine_output_path", return_value="/tmp/out.json"),
            patch.object(service, "_write_batch_output"),
            patch.object(service, "_cleanup_recovery_entries"),
            patch("agent_actions.llm.batch.services.processing_recovery.fire_event"),
        ):
            result = handle_reprompt_recovery(
                service,
                state=state,
                recovery_results=[r1, r2],
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

        # Falls through to exhaustion — should finalize, not return None
        assert result is not None
        service._retry_service.apply_exhausted_reprompt_metadata.assert_called_once()


# ---------------------------------------------------------------------------
# check_and_submit_reprompt tests
# ---------------------------------------------------------------------------


class TestCheckAndSubmitRepromptGraduatedPool:
    """Verify check_and_submit_reprompt uses EvaluationLoop for initial split."""

    def test_uses_evaluation_loop_split(self, _mock_evaluation_imports, mock_loop, mock_strategy):
        """EvaluationLoop.split() is used instead of validate_results()."""
        eval_mod, strat_mod = _mock_evaluation_imports
        strat_mod.ValidationStrategy.return_value = mock_strategy
        eval_mod.EvaluationLoop.return_value = mock_loop

        batch = [_result("r1"), _result("r2")]
        mock_loop.split.return_value = ([_result("r1")], [_result("r2")])

        service = _make_service()

        from agent_actions.llm.batch.services.processing_recovery import (
            check_and_submit_reprompt,
        )

        with patch.object(RecoveryStateManager, "save"):
            result = check_and_submit_reprompt(
                service,
                batch_results=batch,
                context_map={},
                output_directory="/tmp/test",
                file_name="test_file",
                entry=_make_entry(),
                agent_config={"reprompt": {"validation": "v", "max_attempts": 2}},
                manager=MagicMock(),
                provider=MagicMock(),
            )

        # Should have submitted reprompt (returned False)
        assert result is False
        mock_loop.split.assert_called_once_with(batch)
        # validate_results should NOT be called — replaced by loop.split
        service._retry_service.validate_results.assert_not_called()

    def test_all_pass_returns_true(self, _mock_evaluation_imports, mock_loop, mock_strategy):
        """When all results pass evaluation, returns True (no reprompt needed)."""
        eval_mod, strat_mod = _mock_evaluation_imports
        strat_mod.ValidationStrategy.return_value = mock_strategy
        eval_mod.EvaluationLoop.return_value = mock_loop

        batch = [_result("r1"), _result("r2")]
        mock_loop.split.return_value = (batch, [])  # all pass

        from agent_actions.llm.batch.services.processing_recovery import (
            check_and_submit_reprompt,
        )

        result = check_and_submit_reprompt(
            _make_service(),
            batch_results=batch,
            context_map={},
            output_directory="/tmp/test",
            file_name="test_file",
            entry=_make_entry(),
            agent_config={"reprompt": {"validation": "v", "max_attempts": 2}},
            manager=MagicMock(),
            provider=MagicMock(),
        )

        assert result is True

    def test_exhausted_returns_true_and_applies_metadata(
        self, _mock_evaluation_imports, mock_loop, mock_strategy
    ):
        """When current_attempt >= max_attempts, applies exhaustion metadata and returns True."""
        eval_mod, strat_mod = _mock_evaluation_imports
        strat_mod.ValidationStrategy.return_value = mock_strategy
        eval_mod.EvaluationLoop.return_value = mock_loop

        batch = [_result("r1"), _result("r2")]
        mock_loop.split.return_value = ([_result("r1")], [_result("r2")])

        service = _make_service()
        recovery_state = _make_state(reprompt_attempt=2)

        from agent_actions.llm.batch.services.processing_recovery import (
            check_and_submit_reprompt,
        )

        result = check_and_submit_reprompt(
            service,
            batch_results=batch,
            context_map={},
            output_directory="/tmp/test",
            file_name="test_file",
            entry=_make_entry(),
            agent_config={"reprompt": {"validation": "v", "max_attempts": 2}},
            manager=MagicMock(),
            provider=MagicMock(),
            recovery_state=recovery_state,
        )

        assert result is True
        service._retry_service.apply_exhausted_reprompt_metadata.assert_called_once()
        service._retry_service.submit_reprompt_batch.assert_not_called()

    def test_no_reprompt_config_returns_true(self, _mock_evaluation_imports):
        """When reprompt is not configured, returns True immediately."""
        from agent_actions.llm.batch.services.processing_recovery import (
            check_and_submit_reprompt,
        )

        result = check_and_submit_reprompt(
            _make_service(),
            batch_results=[_result("r1")],
            context_map={},
            output_directory="/tmp/test",
            file_name="test_file",
            entry=_make_entry(),
            agent_config={},
            manager=MagicMock(),
            provider=MagicMock(),
        )

        assert result is True

    def test_graduated_saved_to_state(self, _mock_evaluation_imports, mock_loop, mock_strategy):
        """Graduated results are persisted to state.graduated_results."""
        eval_mod, strat_mod = _mock_evaluation_imports
        strat_mod.ValidationStrategy.return_value = mock_strategy
        eval_mod.EvaluationLoop.return_value = mock_loop

        r1 = _result("r1", "pass")
        r2 = _result("r2", "fail")
        mock_loop.split.return_value = ([r1], [r2])

        service = _make_service()
        saved_state = {}

        def capture_save(output_dir, file_name, state):
            saved_state["graduated_results"] = state.graduated_results
            saved_state["evaluation_strategy_name"] = state.evaluation_strategy_name

        from agent_actions.llm.batch.services.processing_recovery import (
            check_and_submit_reprompt,
        )

        with patch.object(RecoveryStateManager, "save", side_effect=capture_save):
            check_and_submit_reprompt(
                service,
                batch_results=[r1, r2],
                context_map={},
                output_directory="/tmp/test",
                file_name="test_file",
                entry=_make_entry(),
                agent_config={"reprompt": {"validation": "v", "max_attempts": 2}},
                manager=MagicMock(),
                provider=MagicMock(),
            )

        # graduated_results should contain serialized r1
        assert len(saved_state["graduated_results"]) == 1
        assert saved_state["graduated_results"][0]["custom_id"] == "r1"
        assert saved_state["evaluation_strategy_name"] == "test_validation"


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
                    "reprompt": {
                        "attempts": 2,
                        "passed": False,
                        "validation": "check_schema",
                    }
                },
            }
        ]

        from agent_actions.llm.batch.services.processing_recovery import (
            write_record_dispositions,
        )

        write_record_dispositions(service, items, "my_action")

        service._storage_backend.set_disposition.assert_called_once_with(
            "my_action",
            "sg-1",
            DISPOSITION_EXHAUSTED,
            reason="evaluation_exhausted:check_schema",
        )

    def test_evaluation_exhausted_takes_precedence_over_retry_exhausted(self):
        """If both _recovery.reprompt.passed=False AND retry_exhausted, evaluation wins."""
        service = _make_service()

        items = [
            {
                "source_guid": "sg-1",
                "metadata": {"retry_exhausted": True},
                "_recovery": {
                    "reprompt": {
                        "attempts": 2,
                        "passed": False,
                        "validation": "check_output",
                    }
                },
            }
        ]

        from agent_actions.llm.batch.services.processing_recovery import (
            write_record_dispositions,
        )

        write_record_dispositions(service, items, "my_action")

        # Should be evaluation_exhausted, not retry_exhausted
        service._storage_backend.set_disposition.assert_called_once()
        reason = service._storage_backend.set_disposition.call_args.kwargs["reason"]
        assert reason == "evaluation_exhausted:check_output"

    def test_retry_exhausted_still_works(self):
        """Existing retry_exhausted path is preserved when no reprompt recovery."""
        service = _make_service()

        items = [
            {
                "source_guid": "sg-1",
                "metadata": {"retry_exhausted": True},
            }
        ]

        from agent_actions.llm.batch.services.processing_recovery import (
            write_record_dispositions,
        )

        write_record_dispositions(service, items, "my_action")

        service._storage_backend.set_disposition.assert_called_once_with(
            "my_action",
            "sg-1",
            DISPOSITION_EXHAUSTED,
            reason="retry_exhausted",
        )

    def test_unknown_validation_fallback(self):
        """Missing validation name defaults to 'unknown'."""
        service = _make_service()

        items = [
            {
                "source_guid": "sg-1",
                "metadata": {},
                "_recovery": {"reprompt": {"passed": False}},
            }
        ]

        from agent_actions.llm.batch.services.processing_recovery import (
            write_record_dispositions,
        )

        write_record_dispositions(service, items, "my_action")

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

        from agent_actions.llm.batch.services.processing_recovery import (
            write_record_dispositions,
        )

        write_record_dispositions(service, items, "my_action")

        # No disposition set (passed=True is not exhausted)
        service._storage_backend.set_disposition.assert_not_called()
