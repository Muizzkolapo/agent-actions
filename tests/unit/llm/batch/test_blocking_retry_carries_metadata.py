"""The blocking retry path prepares its rounds with the run's workflow metadata too.

`retrieve_results_with_retry` resubmits the records the provider did not return and
waits for them. It prepares those rounds the way the non-blocking retry does, so
a prompt or guard reading `workflow.*` renders and evaluates in them as well.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.llm.batch.services.retry_ops import resubmit_missing_records

PREPARATOR = "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
METADATA = {"name": "wf", "run_id": "run_7"}


class _RecordingPreparator:
    instances: list["_RecordingPreparator"] = []

    def __init__(self, **init_kwargs: Any):
        self.prepare_kwargs: dict[str, Any] = {}
        _RecordingPreparator.instances.append(self)

    def prepare_tasks(self, **prepare_kwargs: Any):
        self.prepare_kwargs = prepare_kwargs
        return SimpleNamespace(tasks=[{"custom_id": "rec_1"}])


def test_resubmit_missing_records_hands_the_preparator_the_run_metadata():
    _RecordingPreparator.instances = []
    provider = MagicMock()
    provider.submit_batch.return_value = ("round_batch", 1)
    provider.retrieve_results.return_value = []

    with (
        patch(PREPARATOR, _RecordingPreparator),
        patch(
            "agent_actions.llm.batch.services.retry_ops.wait_for_batch_completion",
            return_value=BatchStatus.COMPLETED,
        ),
    ):
        resubmit_missing_records(
            None,
            provider,
            {"rec_1"},
            {"rec_1": {"target_id": "rec_1"}},
            "/tmp/out",
            "f.json",
            {"name": "act"},
            action_indices={},
            dependency_configs={},
            workflow_metadata=METADATA,
        )

    assert _RecordingPreparator.instances[0].prepare_kwargs["workflow_metadata"] == METADATA


def test_the_service_forwards_the_metadata_from_the_retry_loop_to_the_resubmission():
    service = BatchRetryService(action_indices={}, dependency_configs={}, storage_backend=None)
    context_map = {"id-1": {"prompt": "p"}}
    seen: list[dict[str, Any] | None] = []

    def resubmit(**kwargs):
        seen.append(kwargs["workflow_metadata"])
        return []

    with (
        patch("agent_actions.llm.batch.services.retry.retrieve_and_reconcile", return_value=[]),
        patch("agent_actions.llm.batch.services.retry.time.sleep"),
        patch.object(service, "_resubmit_missing_records", side_effect=resubmit),
        patch(
            "agent_actions.llm.batch.processing.reconciler.BatchResultReconciler.find_missing_ids",
            return_value={"id-1"},
        ),
    ):
        service.retrieve_results_with_retry(
            provider=MagicMock(),
            batch_id="b-1",
            output_directory="/tmp",
            context_map=context_map,
            agent_config={"retry": {"enabled": True, "max_attempts": 2}},
            workflow_metadata=METADATA,
        )

    assert seen and all(m == METADATA for m in seen)


def test_the_service_hands_the_metadata_to_the_resubmission_operation():
    service = BatchRetryService(
        action_indices={"a": 0}, dependency_configs={}, storage_backend=None
    )

    with patch("agent_actions.llm.batch.services.retry._retry.resubmit_missing_records") as resub:
        service._resubmit_missing_records(
            provider=MagicMock(),
            missing_ids={"id-1"},
            context_map={"id-1": {}},
            output_directory="/tmp",
            file_name="f.json",
            agent_config={},
            workflow_metadata=METADATA,
        )

    assert resub.call_args.kwargs["workflow_metadata"] == METADATA
