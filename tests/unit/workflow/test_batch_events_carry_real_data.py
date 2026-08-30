"""Batch lifecycle events must carry real data, or not fire at all.

Four sites in ``executor.py`` fired ``BatchSubmittedEvent``/``BatchCompleteEvent``
from ``action_config``, reading a ``batch_id`` key that nothing in production
ever writes, and hardcoding ``total=1``. Rendered through the event's own
message template that is literally ``"Batch  submitted: 0 requests to "``, and
a four-record batch reported as one record.

Three of the four are duplicates of correctly-populated events fired earlier in
the same call chain — ``submission.py`` for the submit, ``finalize_batch_output``
for the completion — so they are removed rather than repaired. The fourth is the
only signal on its path, so it keeps firing and gets a real source.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.logging.events import BatchCompleteEvent, BatchSubmittedEvent
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ACTION = "summarize_page_content"
CONFIG = {"kind": "llm", "run_mode": "batch", "model_vendor": "ollama_cloud"}


@pytest.fixture
def state_manager(tmp_path):
    return ActionStateManager(tmp_path / ".agent_status.json", [ACTION])


def _executor(state_manager, *, entry: BatchJobEntry | None = None) -> ActionExecutor:
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = state_manager
    deps.action_runner = MagicMock()
    deps.action_runner.action_configs = {ACTION: CONFIG}
    backend = MagicMock()
    backend.has_disposition.side_effect = lambda *a, **k: False
    backend.list_target_files.return_value = ["data.json"]
    backend.get_failed_items.return_value = []
    backend.has_successful_items.return_value = True
    deps.action_runner.storage_backend = backend
    deps.batch_manager = MagicMock()
    deps.batch_manager.registry.get_batch_job.return_value = entry
    return ActionExecutor(deps)


def _fire(executor, batch_status: str) -> list:
    """Drive _resolve_batch_outcome and collect the events it fires."""
    fired: list = []
    with patch("agent_actions.workflow.executor.fire_event", side_effect=fired.append):
        executor._resolve_batch_outcome(
            ACTION, 0, CONFIG, "/out", batch_status, 1.5, pre_run_count=0
        )
    return fired


def _batch_events(fired: list) -> list:
    return [e for e in fired if isinstance(e, BatchSubmittedEvent | BatchCompleteEvent)]


class TestTheDuplicatesAreGone:
    """submission.py and finalize_batch_output already fire these, populated."""

    def test_a_completed_batch_fires_no_duplicate_complete_event(self, state_manager):
        executor = _executor(state_manager)

        assert _batch_events(_fire(executor, "completed")) == []

    def test_an_in_progress_batch_does_not_claim_a_submission(self, state_manager):
        """Nothing was submitted — the poll found the job still running."""
        executor = _executor(state_manager)

        assert _batch_events(_fire(executor, "in_progress")) == []


class TestTheOneRealSignalCarriesRealData:
    """The trailing failure path is the only event-level signal it has."""

    def test_it_reports_the_registry_batch_id_and_count(self, state_manager):
        entry = BatchJobEntry(
            batch_id="batch_abc123",
            status="failed",
            timestamp="2026-08-30T09:00:00",
            provider="ollama_cloud",
            record_count=4,
        )
        executor = _executor(state_manager, entry=entry)

        events = _batch_events(_fire(executor, "failed"))

        assert len(events) == 1
        assert events[0].batch_id == "batch_abc123"
        assert events[0].total == 4, "a four-record batch must not report as one"
        assert events[0].failed == 4

    def test_it_still_fires_when_the_registry_has_no_entry(self, state_manager):
        """Losing the signal entirely would be worse than losing its detail."""
        executor = _executor(state_manager, entry=None)

        events = _batch_events(_fire(executor, "failed"))

        assert len(events) == 1
        assert events[0].action_name == ACTION


class TestTheFreshSubmissionDuplicateIsGone:
    def test_handle_run_success_fires_no_submitted_event(self, state_manager):
        executor = _executor(state_manager)
        params = MagicMock()
        params.action_name = ACTION
        params.action_config = CONFIG
        params.action_idx = 0
        params.start_time = datetime.now()
        params.is_last_action = False

        fired: list = []
        with patch("agent_actions.workflow.executor.fire_event", side_effect=fired.append):
            executor._handle_run_success(params, "/out", 1.0, "submitted", pre_run_count=0)

        assert [e for e in fired if isinstance(e, BatchSubmittedEvent)] == []
        assert state_manager.get_status(ACTION) == ActionStatus.BATCH_SUBMITTED
