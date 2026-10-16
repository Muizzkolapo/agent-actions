"""A first-round retry whose preparation admits no task gives the records up.

`handle_retry_recovery` already treats `RetrySubmissionImpossible` as exhaustion on later
rounds. The first round raised it out of the collect pass instead, so the action failed
and every later run paused on the same finished batch and failed again.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.retry_ops import RetrySubmissionImpossible

PROCESSING = "agent_actions.llm.batch.services.processing"
RETRY = {"retry": {"enabled": True, "max_attempts": 2}}


def _service() -> BatchProcessingService:
    service = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=lambda name: MagicMock(),
        workflow_name="wf",
    )
    service._context_manager.load_batch_context_map.return_value = {
        "rec_1": {"target_id": "rec_1", "source_guid": "g1"},
        "rec_2": {"target_id": "rec_2", "source_guid": "g2"},
    }
    service._retry_service = MagicMock()
    service._finalize_batch_output = MagicMock(return_value="/tmp/out/f.json")
    return service


def _entry() -> BatchJobEntry:
    return BatchJobEntry(
        batch_id="b1", status="completed", timestamp="t", provider="mock", file_name="f.json"
    )


def _collect(service: BatchProcessingService, config: dict):
    with (
        patch(f"{PROCESSING}.retrieve_and_reconcile", return_value=[]),
        patch(f"{PROCESSING}._check_and_submit_repair_impl", return_value=True),
    ):
        return service._process_original_batch(
            "b1", "f.json", _entry(), "/tmp/out", config, MagicMock(), "act"
        )


class TestFirstRoundRetryThatAdmitsNoTask:
    def test_the_file_is_finalized_with_the_lost_records_exhausted(self):
        service = _service()
        service._retry_service.submit_retry_batch.side_effect = RetrySubmissionImpossible(
            "preparation admitted no tasks for f.json"
        )
        service._retry_service.build_exhausted_recovery.return_value = {"rec_1": "meta"}

        output = _collect(service, RETRY)

        assert output == "/tmp/out/f.json"
        exhausted_ids = service._retry_service.build_exhausted_recovery.call_args.args[0]
        assert set(exhausted_ids) == {"rec_1", "rec_2"}
        finalized = service._finalize_batch_output.call_args.kwargs
        assert finalized["exhausted_recovery"] == {"rec_1": "meta"}

    def test_a_transient_submission_failure_does_not_exhaust_anything(self):
        service = _service()
        service._retry_service.submit_retry_batch.return_value = None

        _collect(service, RETRY)

        service._retry_service.build_exhausted_recovery.assert_not_called()
        assert service._finalize_batch_output.call_args.kwargs.get("exhausted_recovery") is None

    def test_an_unrelated_runtime_error_still_fails_the_pass(self):
        service = _service()
        service._retry_service.submit_retry_batch.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            _collect(service, RETRY)

    def test_a_round_that_goes_out_pauses_the_file_and_exhausts_nothing(self):
        service = _service()
        service._retry_service.submit_retry_batch.return_value = ("retry_b", 2)

        with (
            patch(f"{PROCESSING}.register_recovery_batch"),
            patch(f"{PROCESSING}.RecoveryStateManager"),
        ):
            output = _collect(service, RETRY)

        assert output is None
        service._retry_service.build_exhausted_recovery.assert_not_called()
        service._finalize_batch_output.assert_not_called()
