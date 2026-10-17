"""DEFERRED records a recovery batch holds are reported as waiting on it, not as orphans.

Driven through the real lifecycle manager over a SQLite store, with the registry,
recovery state and context map a collect pass leaves behind once it has submitted a
recovery batch. Only records nothing holds are called possible orphans.
"""

from __future__ import annotations

import json
import logging

import pytest

from agent_actions.llm.batch.core.batch_constants import (
    BatchStatus,
    ContextMetaKeys,
    FilterStatus,
    RecoveryPhase,
    RecoveryType,
)
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage.backend import DISPOSITION_DEFERRED
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.managers.batch import BatchLifecycleManager

ACTION = "summarize"
LOGGER_NAME = "agent_actions.workflow.managers.batch"
REFUSED = "{'message': 'Failed to connect to Ollama', 'type': 'ollama_local_error'}"


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    return store


@pytest.fixture
def lifecycle(backend):
    return BatchLifecycleManager(job_manager=None, processing_service=None, storage_backend=backend)


def _defer(backend, *guids: str) -> None:
    for guid in guids:
        backend.set_disposition(ACTION, guid, DISPOSITION_DEFERRED, reason="batch_queued")


def _send(backend, file_name: str, *guids: str) -> None:
    """The original batch of *file_name* sent each guid under the custom id ``c-<guid>``."""
    BatchContextManager.save_batch_context_map(
        backend,
        ACTION,
        {
            f"c-{guid}": {
                "source_guid": guid,
                ContextMetaKeys.FILTER_STATUS: str(FilterStatus.INCLUDED),
            }
            for guid in guids
        },
        file_name,
    )


def _register(backend, file_name: str, *, recovery: RecoveryType | None, collected: bool) -> None:
    parent = file_name.split("_")[0] if recovery else None
    BatchRegistryManager(backend, ACTION).save_batch_job(
        file_name,
        BatchJobEntry(
            batch_id=f"batch-{file_name}",
            status=BatchStatus.SUBMITTED if recovery else BatchStatus.COMPLETED,
            timestamp="2026-10-17T09:00:00+00:00",
            provider="ollama_local",
            record_count=3,
            file_name=file_name,
            parent_file_name=parent,
            recovery_type=recovery,
            recovery_attempt=1 if recovery else None,
            collected_at="2026-10-17T09:05:00+00:00" if collected else None,
        ),
    )


def _retry_pending(backend, *, failed: dict[str, str], unanswered: list[str]) -> None:
    """pages.json's retry batch holds *failed* (guid -> recorded error) and *unanswered*."""
    _register(backend, "pages.json", recovery=None, collected=False)
    _register(backend, "pages.json_retry_1", recovery=RecoveryType.RETRY, collected=False)
    missing = [f"c-{g}" for g in [*failed, *unanswered]]
    RecoveryStateManager.save(
        backend,
        ACTION,
        "pages.json",
        RecoveryState(
            phase=RecoveryPhase.RETRY,
            retry_attempt=1,
            retry_max_attempts=3,
            missing_ids=missing,
            record_failure_counts=dict.fromkeys(missing, 1),
            accumulated_results=[
                {"custom_id": f"c-{g}", "content": None, "success": False, "error": error}
                for g, error in failed.items()
            ],
        ),
    )


def _warnings(caplog, lifecycle) -> str:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        lifecycle._warn_orphaned_deferred(ACTION)
    return caplog.text


def test_records_that_failed_and_wait_on_a_retry_are_reported_with_the_failure(
    backend, lifecycle, caplog
):
    _send(backend, "pages.json", "g1", "g2")
    _defer(backend, "g1", "g2")
    _retry_pending(backend, failed={"g1": REFUSED, "g2": REFUSED}, unanswered=[])

    text = _warnings(caplog, lifecycle)

    assert "orphan" not in text.lower(), text
    assert (
        "2 record(s) wait on retry attempt 2 of 3 after their last attempt failed: "
        f"{REFUSED}: ['g1', 'g2']"
    ) in text


def test_a_mix_names_each_failure_the_unanswered_records_and_the_orphans_apart(
    backend, lifecycle, caplog
):
    _send(backend, "pages.json", "g1", "g2", "g3", "g4")
    _defer(backend, "g1", "g2", "g3", "g4", "lost")
    _retry_pending(
        backend,
        failed={"g1": REFUSED, "g2": "rate limited"},
        unanswered=["g3", "g4"],
    )

    text = _warnings(caplog, lifecycle)

    assert (
        f"1 record(s) wait on retry attempt 2 of 3 after their last attempt failed: {REFUSED}: ['g1']"
        in text
    )
    assert (
        "1 record(s) wait on retry attempt 2 of 3 after their last attempt failed: rate limited: ['g2']"
        in text
    )
    assert (
        "2 record(s) wait on retry attempt 2 of 3: the provider returned no result for them: "
        "['g3', 'g4']"
    ) in text
    assert (
        "1 record(s) still in DEFERRED state after batch completion — possible orphans: ['lost']"
        in text
    )


def test_records_wait_on_a_repair_round(backend, lifecycle, caplog):
    _send(backend, "pages.json", "g1")
    _defer(backend, "g1")
    _register(backend, "pages.json", recovery=None, collected=False)
    _register(backend, "pages.json_repair_1", recovery=RecoveryType.REPAIR, collected=False)
    RecoveryStateManager.save(
        backend,
        ACTION,
        "pages.json",
        RecoveryState(
            phase=RecoveryPhase.REPAIR,
            repair_attempt=1,
            repair_max_attempts=2,
            repair_submitted_ids=["c-g1"],
        ),
    )

    text = _warnings(caplog, lifecycle)

    assert "orphan" not in text.lower(), text
    assert "1 record(s) wait on repair round 1 of 2: ['g1']" in text


def test_a_collected_recovery_holds_nothing(backend, lifecycle, caplog):
    _send(backend, "pages.json", "g1")
    _defer(backend, "g1")
    _retry_pending(backend, failed={"g1": REFUSED}, unanswered=[])
    _register(backend, "pages.json_retry_1", recovery=RecoveryType.RETRY, collected=True)

    text = _warnings(caplog, lifecycle)

    assert (
        "1 record(s) still in DEFERRED state after batch completion — possible orphans: ['g1']"
        in text
    )
    assert "wait on" not in text


def test_an_unreadable_recovery_state_leaves_the_records_called_orphans(backend, lifecycle, caplog):
    _send(backend, "pages.json", "g1")
    _defer(backend, "g1")
    _retry_pending(backend, failed={"g1": REFUSED}, unanswered=[])
    backend.save_metadata(f"recovery_state:{ACTION}:pages.json", json.dumps({"bogus": 1}))

    text = _warnings(caplog, lifecycle)

    assert "possible orphans: ['g1']" in text
