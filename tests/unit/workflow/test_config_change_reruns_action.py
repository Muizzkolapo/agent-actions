"""A completed action must re-run when its config changed.

``execute_action_sync`` checks for a config change before checking for output,
and that order is correct.  But the coordinator never reaches it for a completed
action: both run loops call ``verify_completion_status(action_name)`` first, and
that function takes only a name — it has no ``action_config``, so it can only
ask "does the output still exist".  For any completed action that still has its
output, it says "skip", and the invalidation check never runs.  Edit a guard, a
prompt, a model or a schema, re-run, and the previous run's results come back
with nothing said about it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_actions.workflow.executor import (
    ActionExecutor,
    ExecutorDependencies,
    _compute_action_config_hash,
)
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ACTION = "extract_candidates"


def _config(condition: str) -> dict:
    """An expanded action config — the shape the hash actually reads."""
    return {
        "agent_type": ACTION,
        "kind": "llm",
        "prompt": "$wf.Extract",
        "guard": {"clause": condition, "scope": "item", "behavior": "filter"},
    }


@pytest.fixture
def state_manager(tmp_path):
    return ActionStateManager(tmp_path / ".agent_status.json", [ACTION])


def _executor(state_manager, action_config: dict, *, has_output: bool = True) -> ActionExecutor:
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = state_manager
    deps.action_runner = MagicMock()
    deps.action_runner.action_configs = {ACTION: action_config}
    backend = MagicMock()
    # No blocking disposition: the prior-output check treats FAILED/SKIPPED at
    # node level as "re-run regardless", which would mask the config question.
    backend.has_disposition.side_effect = lambda *a, **k: False
    backend.list_target_files.return_value = ["data.json"] if has_output else []
    deps.action_runner.storage_backend = backend
    return ActionExecutor(deps)


def _complete_with(state_manager, action_config: dict) -> None:
    """Mark the action completed, stamped with that config's hash — as a real run does."""
    state_manager.update_status(
        ACTION,
        ActionStatus.COMPLETED,
        record_limit=action_config.get("record_limit"),
        file_limit=action_config.get("file_limit"),
        config_hash=_compute_action_config_hash(action_config),
    )


class TestAChangedConfigReRunsTheAction:
    def test_a_changed_guard_is_not_skipped(self, state_manager):
        _complete_with(state_manager, _config('density == "high"'))
        executor = _executor(state_manager, _config('density == "impossible"'))

        assert executor.verify_completion_status(ACTION) is False

    def test_a_changed_guard_returns_the_action_to_pending(self, state_manager):
        _complete_with(state_manager, _config('density == "high"'))
        executor = _executor(state_manager, _config('density == "impossible"'))

        executor.verify_completion_status(ACTION)

        assert state_manager.get_status(ACTION) == ActionStatus.PENDING

    def test_a_changed_record_limit_is_not_skipped(self, state_manager):
        before = _config('density == "high"')
        _complete_with(state_manager, before)
        after = dict(before, record_limit=5)
        executor = _executor(state_manager, after)

        assert executor.verify_completion_status(ACTION) is False


class TestAnUnchangedConfigIsStillSkipped:
    """Re-running an untouched workflow must not redo completed work."""

    def test_the_same_config_skips(self, state_manager):
        config = _config('density == "high"')
        _complete_with(state_manager, config)
        executor = _executor(state_manager, config)

        assert executor.verify_completion_status(ACTION) is True
        assert state_manager.get_status(ACTION) == ActionStatus.COMPLETED

    def test_missing_output_still_re_runs(self, state_manager):
        config = _config('density == "high"')
        _complete_with(state_manager, config)
        executor = _executor(state_manager, config, has_output=False)

        assert executor.verify_completion_status(ACTION) is False

    def test_a_status_without_a_stored_hash_is_left_alone(self, state_manager):
        """Pre-existing state from before hashing must not all invalidate at once."""
        state_manager.update_status(ACTION, ActionStatus.COMPLETED)
        executor = _executor(state_manager, _config('density == "high"'))

        assert executor.verify_completion_status(ACTION) is True

    def test_an_action_with_no_known_config_falls_back_to_the_output_check(self, state_manager):
        config = _config('density == "high"')
        _complete_with(state_manager, config)
        executor = _executor(state_manager, config)
        executor.deps.action_runner.action_configs = {}

        assert executor.verify_completion_status(ACTION) is True
