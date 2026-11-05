"""What a completed action does on the next run when its config changed.

Both run loops reach a completed action through ``verify_completion_status``, which
reads the config the action runs under and compares it with the completion stamp. A
changed limit re-runs the action. An edit to its guard, prompt, schema or model does
not: the answers it holds stand, a warning names the edit, and ``--rerun`` applies it.
"""

from __future__ import annotations

import logging
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
    deps.action_runner.staged_input_fingerprint.return_value = None
    deps.action_runner.retried_records = frozenset()
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
        **_executor(state_manager, action_config)._completion_metadata(ACTION, action_config),
    )


class TestAChangedConfigOnACompletedAction:
    @pytest.mark.parametrize(
        ("before", "change", "label"),
        [
            pytest.param(
                _config('density == "high"'),
                {"guard": _config('density == "impossible"')["guard"]},
                "action config (prompt/schema/guard)",
                id="guard",
            ),
            # The hash cannot see the model, so it is compared from the stamp.
            pytest.param(
                dict(
                    _config('density == "high"'), model_name="gpt-oss:120b", model_vendor="ollama"
                ),
                {"model_name": "claude-sonnet-4"},
                "model",
                id="model_name",
            ),
            pytest.param(
                dict(_config('density == "high"'), model_name="m", model_vendor="ollama"),
                {"model_vendor": "anthropic"},
                "model",
                id="model_vendor",
            ),
        ],
    )
    def test_an_edited_action_is_skipped_and_the_edit_named(
        self, state_manager, caplog, before, change, label
    ):
        _complete_with(state_manager, before)
        executor = _executor(state_manager, dict(before, **change))

        with caplog.at_level(logging.WARNING, logger="agent_actions"):
            assert executor.verify_completion_status(ACTION) is True

        assert state_manager.get_status(ACTION) == ActionStatus.COMPLETED
        executor.deps.action_runner.storage_backend.clear_disposition.assert_not_called()
        assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [
            f"{ACTION} was edited since it completed ({label}): its answers stand, and only "
            f"records it has not answered use the edit. Run again with --rerun {ACTION} to "
            "answer every record under the edit"
        ]

    def test_a_changed_record_limit_is_not_skipped(self, state_manager):
        config = _config('density == "high"')
        _complete_with(state_manager, config)
        executor = _executor(state_manager, dict(config, record_limit=5))

        assert executor.verify_completion_status(ACTION) is False
        assert state_manager.get_status(ACTION) == ActionStatus.PENDING

    def test_a_stale_verdict_is_wiped_for_the_whole_action(self, state_manager):
        """A changed limit makes every per-record verdict stale.

        Checking output first would clear only the node-level marker and leave
        per-record SUCCESS rows, which the disposition gate carries forward — so
        the action would re-run while skipping records that already succeeded.
        """
        config = _config('density == "high"')
        _complete_with(state_manager, config)
        executor = _executor(state_manager, dict(config, record_limit=5), has_output=False)

        executor.verify_completion_status(ACTION)

        backend = executor.deps.action_runner.storage_backend
        assert backend.clear_disposition.call_args_list == [(("extract_candidates",), {})]


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
        legacy = _executor(state_manager, config)._completion_metadata(ACTION, config)
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
