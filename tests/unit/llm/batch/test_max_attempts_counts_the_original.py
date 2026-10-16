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
