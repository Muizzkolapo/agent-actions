"""`retry.max_attempts` counts the original batch as an attempt, as online does."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.infrastructure.recovery_state import retries_left
from agent_actions.llm.batch.services.retry import BatchRetryService


@pytest.mark.parametrize(
    ("retries_sent", "max_attempts", "left"),
    [(0, 1, 0), (0, 2, 1), (1, 2, 0), (1, 3, 1), (2, 3, 0), (0, 10, 9), (3, 3, -1)],
)
def test_retries_left_is_what_remains_after_the_original_batch(retries_sent, max_attempts, left):
    assert retries_left(retries_sent, max_attempts) == left


def _lost_forever(max_attempts: int):
    """Run the synchronous retry loop over one record no batch ever answers."""
    service = BatchRetryService.__new__(BatchRetryService)
    resubmit = MagicMock(return_value=[])
    with (
        patch("agent_actions.llm.batch.services.retry.retrieve_and_reconcile", return_value=[]),
        patch("agent_actions.llm.batch.services.retry.time.sleep"),
        patch.object(service, "_resubmit_missing_records", resubmit),
        patch(
            "agent_actions.llm.batch.processing.reconciler.BatchResultReconciler.find_missing_ids",
            return_value={"id-1"},
        ),
        patch(
            "agent_actions.llm.batch.processing.reconciler.BatchResultReconciler.collect_result_custom_ids",
            return_value=set(),
        ),
    ):
        _, exhausted = service.retrieve_results_with_retry(
            provider=MagicMock(),
            batch_id="b-1",
            output_directory="/tmp",
            context_map={"id-1": {"prompt": "p"}},
            agent_config={"retry": {"enabled": True, "max_attempts": max_attempts}},
        )
    return resubmit.call_count, exhausted


@pytest.mark.parametrize("max_attempts", [1, 2, 3])
def test_the_synchronous_loop_resubmits_one_fewer_time_than_max_attempts(max_attempts):
    resubmitted, exhausted = _lost_forever(max_attempts)

    assert resubmitted == max_attempts - 1
    assert exhausted["id-1"].retry.attempts == max_attempts
    assert exhausted["id-1"].retry.succeeded is False


def _original_batch(max_attempts: int, submitted_retry):
    """Drive the original-batch path over one record the provider never answered.

    Returns what the path handed the repair check and the finaliser, and whether it returned
    because a recovery batch went out.
    """
    from agent_actions.llm.batch.core.batch_models import BatchJobEntry
    from agent_actions.llm.batch.services.processing import BatchProcessingService

    service = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=MagicMock(),
        action_indices={},
        dependency_configs={},
        storage_backend=MagicMock(),
        workflow_name="act",
    )
    service._context_manager.load_batch_context_map.return_value = {
        "r1": {"target_id": "r1", "source_guid": "sg-r1", "content": {"source": {"t": "x"}}}
    }
    entry = BatchJobEntry(
        batch_id="b-1", status="completed", timestamp="t", provider="p", file_name="f.json"
    )
    seen: dict = {}

    def _repair_check(**kwargs):
        seen["recovery_state"] = kwargs["recovery_state"]
        return True

    submit = MagicMock(return_value=submitted_retry)
    with (
        patch(
            "agent_actions.llm.batch.services.processing.retrieve_and_reconcile", return_value=[]
        ),
        patch(
            "agent_actions.llm.batch.services.processing._check_and_submit_repair_impl",
            side_effect=_repair_check,
        ),
        patch.object(service._retry_service, "submit_retry_batch", submit),
        patch.object(service, "_finalize_batch_output", return_value="/out.json") as finalize,
        patch("agent_actions.llm.batch.services.processing.register_recovery_batch"),
        patch("agent_actions.llm.batch.services.processing.RecoveryStateManager"),
    ):
        returned = service._process_original_batch(
            batch_id="b-1",
            file_name="f.json",
            entry=entry,
            output_directory="/out",
            agent_config={"retry": {"enabled": True, "max_attempts": max_attempts}},
            manager=MagicMock(),
            action_name="act",
        )
    return returned, seen, submit, finalize


def test_an_action_that_allows_one_attempt_is_exhausted_by_its_original_batch():
    returned, seen, submit, finalize = _original_batch(1, submitted_retry=("rb-1", 1))

    submit.assert_not_called()
    assert returned == "/out.json"
    exhausted = finalize.call_args.kwargs["exhausted_recovery"]
    assert exhausted["r1"].retry.attempts == 1
    assert exhausted["r1"].retry.succeeded is False
    # What a repair round carries forward: finalisation rebuilds the stamp from these.
    assert seen["recovery_state"].missing_ids == ["r1"]
    assert seen["recovery_state"].record_failure_counts == {"r1": 1}


def test_an_action_that_allows_two_attempts_sends_its_one_retry_instead():
    returned, seen, submit, finalize = _original_batch(2, submitted_retry=("rb-1", 1))

    submit.assert_called_once()
    assert returned is None
    assert seen == {}
    finalize.assert_not_called()
