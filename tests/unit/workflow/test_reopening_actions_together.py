"""Putting an action and what reads it back to pending, as the next process finds it."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import (
    ActionExecutor,
    ExecutorDependencies,
    _compute_action_config_hash,
)
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

NAMES = ["split", "define", "grade"]


def test_reopen_leaves_no_moment_where_only_some_are_pending(tmp_path):
    """One write for all of them. A second, were there one, is where a process can die
    with the action pending and what reads it still completed."""
    status_file = tmp_path / "status.json"
    state = ActionStateManager(status_file, NAMES)
    for name in NAMES:
        state.update_status(name, ActionStatus.COMPLETED)
    save = state._save_status
    writes = []

    def one_write_only():
        writes.append(1)
        if len(writes) > 1:
            raise OSError("the process died here")
        save()

    state._save_status = one_write_only

    state.reopen(NAMES)

    next_process = ActionStateManager(status_file, NAMES)
    assert [next_process.get_status(name) for name in NAMES] == [ActionStatus.PENDING] * 3


def test_a_completed_reader_is_not_said_to_give_up_a_batch_it_collected_long_ago(tmp_path, caplog):
    """An entry written before `collected_at` existed has no stamp. The reader completed,
    so the batch was collected, and the warning would name a batch nobody is waiting on."""
    configs = {
        "split": {"prompt": "X", "model": "m"},
        "define": {"prompt": "X", "model": "m", "dependencies": ["split"]},
    }
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    state = ActionStateManager(tmp_path / "status.json", list(configs))
    for name, config in configs.items():
        state.update_status(
            name, ActionStatus.COMPLETED, config_hash=_compute_action_config_hash(config)
        )
    BatchRegistryManager(backend, "define").save_batch_job(
        "page.json",
        BatchJobEntry(batch_id="b_old", status="completed", timestamp="t", provider="p"),
    )
    runner = MagicMock()
    runner.retried_records = frozenset()
    runner.storage_backend = backend
    runner.action_configs = configs
    executor = ActionExecutor(
        ExecutorDependencies(
            action_runner=runner,
            state_manager=state,
            skip_evaluator=MagicMock(),
            batch_manager=MagicMock(),
            output_manager=MagicMock(),
        )
    )

    with caplog.at_level(logging.WARNING, logger="agent_actions"):
        executor._maybe_invalidate_completed_status(
            "split", {**configs["split"], "prompt": "Y"}, ActionStatus.COMPLETED
        )

    assert state.get_status("define") == ActionStatus.PENDING
    assert [r.getMessage() for r in caplog.records if "giving up" in r.getMessage()] == []


def test_a_retry_says_so_for_the_edited_action_it_is_about_to_re_run(tmp_path, caplog):
    """Retry has put it back to pending. It answers the named records under the edit,
    and the records it did not name still hold what the old config wrote."""
    config = {"prompt": "X", "model": "m"}
    state = ActionStateManager(tmp_path / "status.json", ["split"])
    state.update_status(
        "split", ActionStatus.COMPLETED, config_hash=_compute_action_config_hash(config)
    )
    state.update_status("split", ActionStatus.PENDING)
    runner = MagicMock()
    runner.retried_records = frozenset({"r1"})
    executor = ActionExecutor(
        ExecutorDependencies(
            action_runner=runner,
            state_manager=state,
            skip_evaluator=MagicMock(),
            batch_manager=MagicMock(),
            output_manager=MagicMock(),
        )
    )

    with caplog.at_level(logging.WARNING, logger="agent_actions"):
        status = executor._maybe_invalidate_completed_status(
            "split", {**config, "prompt": "Y"}, ActionStatus.PENDING
        )

    assert status == ActionStatus.PENDING
    assert [r.getMessage() for r in caplog.records if "agac run" in r.getMessage()] != []
