"""The batch manager hands the run's workflow metadata to the collect pass.

Retry and repair rounds are prepared while a batch is collected, so the metadata
has to travel from `handle_batch_agent` to `process_all_batch_results` on both
routes that collect: a registry that reads completed, and one that reads
in progress until every job has finished.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.managers.batch import BatchLifecycleManager

METADATA = {"name": "wf", "run_id": "run_7"}
CONFIG = {"kind": "llm"}


@pytest.fixture
def parts():
    job_manager = MagicMock()
    processing_service = MagicMock()
    backend = MagicMock()
    backend.has_disposition.return_value = False
    backend.load_metadata.return_value = None
    manager = BatchLifecycleManager(job_manager, processing_service, storage_backend=backend)
    return manager, job_manager, processing_service


class TestCollectPassReceivesTheRunsMetadata:
    @pytest.mark.parametrize(
        ("registry", "all_done"),
        [
            pytest.param("completed", None, id="registry_reads_completed"),
            pytest.param("in_progress", True, id="in_progress_but_every_job_finished"),
        ],
    )
    def test_the_collect_pass_receives_the_metadata(self, parts, registry, all_done):
        manager, job_manager, processing_service = parts
        job_manager.get_registry_status.return_value = registry
        job_manager.are_all_jobs_completed.return_value = all_done

        with patch("agent_actions.workflow.managers.batch.fire_event"):
            manager.handle_batch_agent("act", "/out", CONFIG, workflow_metadata=METADATA)

        sent = processing_service.process_all_batch_results.call_args.kwargs
        assert sent["workflow_metadata"] == METADATA

    def test_a_call_without_metadata_collects_with_none(self, parts):
        manager, job_manager, processing_service = parts
        job_manager.get_registry_status.return_value = "completed"

        with patch("agent_actions.workflow.managers.batch.fire_event"):
            manager.handle_batch_agent("act", "/out", CONFIG)

        sent = processing_service.process_all_batch_results.call_args.kwargs
        assert sent["workflow_metadata"] is None
