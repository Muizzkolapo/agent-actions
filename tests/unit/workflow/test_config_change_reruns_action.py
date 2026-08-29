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

from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
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
    """Mark the action completed the way a real run stamps it."""
    state_manager.update_status(
        ACTION,
        ActionStatus.COMPLETED,
        **ActionExecutor._completion_metadata(action_config),
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

    def test_a_changed_model_is_not_skipped(self, state_manager):
        """The hash cannot see the model, so it is compared from the stamp."""
        before = dict(
            _config('density == "high"'), model_name="gpt-oss:120b", model_vendor="ollama"
        )
        _complete_with(state_manager, before)
        after = dict(before, model_name="claude-sonnet-4")
        executor = _executor(state_manager, after)

        assert executor.verify_completion_status(ACTION) is False

    def test_a_changed_model_vendor_is_not_skipped(self, state_manager):
        before = dict(_config('density == "high"'), model_name="m", model_vendor="ollama")
        _complete_with(state_manager, before)
        after = dict(before, model_vendor="anthropic")
        executor = _executor(state_manager, after)

        assert executor.verify_completion_status(ACTION) is False

    def test_a_stale_verdict_is_wiped_for_the_whole_action(self, state_manager):
        """A changed prompt or guard makes every per-record verdict stale.

        Checking output first would clear only the node-level marker and leave
        per-record SUCCESS rows, which the disposition gate carries forward — so
        the action would re-run while skipping records that already succeeded.
        """
        _complete_with(state_manager, _config('density == "high"'))
        executor = _executor(state_manager, _config('density == "impossible"'), has_output=False)

        executor.verify_completion_status(ACTION)

        backend = executor.deps.action_runner.storage_backend
        assert backend.clear_disposition.call_args_list == [(("extract_candidates",), {})]

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

    def test_state_predating_the_model_stamp_does_not_invalidate(self, state_manager):
        """The migration case, and the reason the model is not folded into the hash.

        A status written before the model was stamped has no stored model, while
        the config has one. Treating "absent" as "changed" would invalidate every
        completed action in every workflow at once, on the first run after upgrade.
        """
        config = dict(
            _config('density == "high"'), model_name="gpt-oss:120b", model_vendor="ollama"
        )
        legacy = ActionExecutor._completion_metadata(config)
        del legacy["model_name"]
        del legacy["model_vendor"]
        state_manager.update_status(ACTION, ActionStatus.COMPLETED, **legacy)
        executor = _executor(state_manager, config)

        assert executor.verify_completion_status(ACTION) is True
        assert state_manager.get_status(ACTION) == ActionStatus.COMPLETED

    def test_an_action_with_no_known_config_falls_back_to_the_output_check(self, state_manager):
        config = _config('density == "high"')
        _complete_with(state_manager, config)
        executor = _executor(state_manager, config)
        executor.deps.action_runner.action_configs = {}

        assert executor.verify_completion_status(ACTION) is True
