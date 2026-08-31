"""A halt must escape the batch result loop even when another file processed.

The loop tolerates a per-file failure so one bad batch cannot abandon the
rest. An ``on_exhausted: raise`` halt is not that: swallowing it drops the
policy, leaves no halt marker, and the next run resubmits the batch — the
provider bill repeating for a failure the config asked to stop on.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import AgentActionsError, raised_by_exhaustion_policy
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.processing import BatchProcessingService

ACTION = "label_page"
AGENT_CONFIG = {"kind": "llm", "retry": {"enabled": True, "on_exhausted": "raise"}}


def _entry(batch_id: str, file_name: str) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id=batch_id,
        status=BatchStatus.COMPLETED,
        timestamp="2026-08-31T09:00:00+00:00",
        provider="ollama_local",
        record_count=1,
        file_name=file_name,
    )


def _halt() -> AgentActionsError:
    """The exhaustion halt the result collector raises on the batch path."""
    return AgentActionsError(
        "Retry exhausted for record r-2 after 2 attempts (on_exhausted=raise)",
        context={"agent_name": ACTION, "on_exhausted": "raise"},
    )


def _service(manager: MagicMock) -> BatchProcessingService:
    return BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=lambda _: manager,
        storage_backend=MagicMock(),
        workflow_name=ACTION,
    )


def _manager() -> MagicMock:
    jobs = {
        "ok.json": _entry("batch_ok", "ok.json"),
        "halted.json": _entry("batch_halted", "halted.json"),
    }
    manager = MagicMock()
    manager.get_all_jobs.return_value = jobs
    manager.get_batch_job.side_effect = jobs.get
    manager.get_registry_stats.return_value = MagicMock(in_progress=0)
    return manager


class TestAHaltEscapesTheBatchLoop:
    def test_a_halt_after_a_successful_file_is_raised(self):
        manager = _manager()
        service = _service(manager)
        halt = _halt()

        def process_one(*, batch_id, **_kw):
            if batch_id == "batch_halted":
                raise halt
            return "/out/ok.json"

        with (
            patch.object(service, "_is_batch_ready_for_processing", return_value=True),
            patch.object(service, "_process_single_batch_file", side_effect=process_one),
            patch.object(service, "_fail_abandoned_records") as abandoned,
        ):
            with pytest.raises(AgentActionsError) as exc_info:
                service.process_all_batch_results("/out", AGENT_CONFIG, action_name=ACTION)

        assert raised_by_exhaustion_policy(exc_info.value), (
            "the halt was swallowed, so no halt marker is written and the "
            "next run resubmits the batch at the provider's price"
        )
        assert abandoned.call_count == 0, (
            "the halted file's exhausted dispositions were overwritten as abandoned"
        )

    def test_an_ordinary_per_file_failure_still_does_not_stop_the_others(self):
        """The tolerance the loop exists for must survive."""
        manager = _manager()
        service = _service(manager)

        def process_one(*, batch_id, **_kw):
            if batch_id == "batch_halted":
                raise ValueError("unreadable batch output")
            return "/out/ok.json"

        with (
            patch.object(service, "_is_batch_ready_for_processing", return_value=True),
            patch.object(service, "_process_single_batch_file", side_effect=process_one),
            patch.object(service, "_fail_abandoned_records") as abandoned,
        ):
            processed = service.process_all_batch_results("/out", AGENT_CONFIG, action_name=ACTION)

        assert processed == ["/out/ok.json"]
        assert abandoned.call_count == 1
