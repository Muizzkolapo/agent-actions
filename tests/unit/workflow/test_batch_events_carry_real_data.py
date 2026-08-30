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

import json
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


def _executor(state_manager, *, jobs: dict[str, BatchJobEntry] | None = None) -> ActionExecutor:
    """Executor whose registry really answers, through the metadata it reads.

    ``jobs`` is keyed by input file, the way the registry actually stores it.
    Mocking a lookup *by action name* is what let the first version of this fix
    pass its tests while doing nothing on a live run.
    """
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = state_manager
    deps.action_runner = MagicMock()
    deps.action_runner.action_configs = {ACTION: CONFIG}
    backend = MagicMock()
    backend.has_disposition.side_effect = lambda *a, **k: False
    backend.list_target_files.return_value = ["data.json"]
    backend.get_failed_items.return_value = []
    backend.has_successful_items.return_value = True
    backend.load_metadata.side_effect = lambda key: (
        json.dumps({f: e.to_dict() for f, e in jobs.items()})
        if jobs and key == f"batch_registry:{ACTION}"
        else None
    )
    deps.action_runner.storage_backend = backend
    deps.batch_manager = MagicMock()
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
        executor = _executor(state_manager, jobs={"pages.json": entry})

        events = _batch_events(_fire(executor, "failed"))

        assert len(events) == 1
        assert events[0].batch_id == "batch_abc123"
        assert events[0].total == 4, "a four-record batch must not report as one"
        assert events[0].failed == 4

    def test_it_sums_the_records_across_an_action_s_jobs(self, state_manager):
        """One action owns one job per input file, so the count is a sum."""
        executor = _executor(
            state_manager,
            jobs={
                "a.json": BatchJobEntry(
                    batch_id="batch_a",
                    status="failed",
                    timestamp="2026-08-30T09:00:00",
                    provider="ollama_cloud",
                    record_count=4,
                ),
                "b.json": BatchJobEntry(
                    batch_id="batch_b",
                    status="failed",
                    timestamp="2026-08-30T09:00:00",
                    provider="ollama_cloud",
                    record_count=3,
                ),
            },
        )

        events = _batch_events(_fire(executor, "failed"))

        assert events[0].total == 7
        assert events[0].failed == 7
        assert events[0].batch_id == "", "two jobs have no single batch id to name"

    def test_it_says_nothing_when_the_registry_cannot_give_a_count(self, state_manager):
        """An invented total is indistinguishable from a real one.

        This is the count someone reads to size an outage, and the empty
        registry is reachable — a rebuilt store leaves an action stamped
        BATCH_SUBMITTED with no jobs behind it. ``ActionFailedEvent`` still
        reports the failure, so nothing is silenced by declining to guess.
        """
        executor = _executor(state_manager, jobs=None)

        assert _batch_events(_fire(executor, "failed")) == []

    def test_it_ignores_recovery_entries_when_counting(self, state_manager):
        """Recovery jobs re-submit a subset of a parent's records.

        They live under their own registry key, so summing every entry counts
        the retried records twice.
        """
        parent = BatchJobEntry(
            batch_id="batch_parent",
            status="failed",
            timestamp="2026-08-30T09:00:00",
            provider="ollama_cloud",
            record_count=3,
        )
        retry = BatchJobEntry(
            batch_id="batch_retry",
            status="failed",
            timestamp="2026-08-30T09:05:00",
            provider="ollama_cloud",
            record_count=2,
            parent_file_name="pages.json",
            recovery_attempt=1,
        )
        executor = _executor(
            state_manager, jobs={"pages.json": parent, "pages.json_retry_1": retry}
        )

        events = _batch_events(_fire(executor, "failed"))

        assert events[0].total == 3, "the two retried records are not extra records"
        assert events[0].batch_id == "batch_parent"


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
            executor._handle_run_success(params, "/out", 1.0, "batch_submitted", pre_run_count=0)

        assert [e for e in fired if isinstance(e, BatchSubmittedEvent)] == []
        assert state_manager.get_status(ACTION) == ActionStatus.BATCH_SUBMITTED


class TestTheSurvivingEventsNameTheAction:
    """Removing the duplicates must not lose the action name.

    The duplicates carried the real action name and nothing else; the populated
    events carried real batch data under the *file key* (``pages.json``). Both
    call sites already have the action name in scope — ``submission.py`` uses it
    two lines below as ``registry_name``, and ``finalize_batch_output`` resolves
    it into ``effective_action_name``.
    """

    def test_submission_names_the_action_not_the_file_key(self):
        from agent_actions.llm.batch.services.submission import BatchSubmissionService

        service = object.__new__(BatchSubmissionService)
        provider = MagicMock()
        provider.submit_batch.return_value = ("batch_xyz", "submitted")
        service._client_resolver = MagicMock()
        service._client_resolver.get_for_config.return_value = provider
        service._registry_manager_factory = MagicMock()

        fired: list = []
        with (
            patch(
                "agent_actions.llm.batch.services.submission.fire_event", side_effect=fired.append
            ),
            patch("agent_actions.llm.batch.services.submission.get_manager"),
        ):
            service._submit_to_provider(
                {"model_vendor": "ollama_cloud"},
                "pages.json",
                [{"a": 1}, {"b": 2}, {"c": 3}],
                None,
                ACTION,
            )

        submitted = [e for e in fired if isinstance(e, BatchSubmittedEvent)]
        assert len(submitted) == 1
        assert submitted[0].action_name == ACTION, "named the file key, not the action"
        assert submitted[0].batch_id == "batch_xyz"
        assert submitted[0].request_count == 3
