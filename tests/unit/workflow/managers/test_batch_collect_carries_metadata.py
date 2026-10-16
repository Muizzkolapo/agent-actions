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
    def test_when_the_registry_reads_completed(self, parts):
        manager, job_manager, processing_service = parts
        job_manager.get_registry_status.return_value = "completed"

        with patch("agent_actions.workflow.managers.batch.fire_event"):
            manager.handle_batch_agent("act", "/out", CONFIG, workflow_metadata=METADATA)

        sent = processing_service.process_all_batch_results.call_args.kwargs
        assert sent["workflow_metadata"] == METADATA

    def test_when_every_job_finished_while_the_registry_read_in_progress(self, parts):
        manager, job_manager, processing_service = parts
        job_manager.get_registry_status.return_value = "in_progress"
        job_manager.are_all_jobs_completed.return_value = True

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
