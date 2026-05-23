"""Tests for config change detection via action hash."""

from unittest.mock import MagicMock

from agent_actions.workflow.executor import (
    ActionExecutor,
    ExecutorDependencies,
    _compute_action_config_hash,
)
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


class TestComputeActionConfigHash:
    """_compute_action_config_hash must produce stable, deterministic hashes."""

    def test_same_config_produces_same_hash(self):
        config = {"prompt": "Summarize", "model": "gpt-4", "schema": "s.yml"}
        assert _compute_action_config_hash(config) == _compute_action_config_hash(config)

    def test_different_model_produces_different_hash(self):
        base = {"prompt": "Summarize", "model": "gpt-4", "schema": "s.yml"}
        changed = {**base, "model": "gpt-4o"}
        assert _compute_action_config_hash(base) != _compute_action_config_hash(changed)

    def test_different_prompt_produces_different_hash(self):
        base = {"prompt": "Summarize", "model": "gpt-4"}
        changed = {**base, "prompt": "Analyze"}
        assert _compute_action_config_hash(base) != _compute_action_config_hash(changed)

    def test_different_schema_produces_different_hash(self):
        base = {"prompt": "Summarize", "model": "gpt-4", "schema": "old.yml"}
        changed = {**base, "schema": "new.yml"}
        assert _compute_action_config_hash(base) != _compute_action_config_hash(changed)

    def test_different_guard_clause_produces_different_hash(self):
        base = {"prompt": "X", "guard": {"clause": "a > 1", "behavior": "skip"}}
        changed = {"prompt": "X", "guard": {"clause": "a > 2", "behavior": "skip"}}
        assert _compute_action_config_hash(base) != _compute_action_config_hash(changed)

    def test_different_guard_behavior_produces_different_hash(self):
        base = {"prompt": "X", "guard": {"clause": "a > 1", "behavior": "skip"}}
        changed = {"prompt": "X", "guard": {"clause": "a > 1", "behavior": "warn"}}
        assert _compute_action_config_hash(base) != _compute_action_config_hash(changed)

    def test_cosmetic_description_change_does_not_change_hash(self):
        base = {"prompt": "X", "model": "m", "description": "Old desc"}
        changed = {**base, "description": "New desc"}
        assert _compute_action_config_hash(base) == _compute_action_config_hash(changed)

    def test_limit_change_does_not_change_hash(self):
        base = {"prompt": "X", "model": "m", "record_limit": 10}
        changed = {**base, "record_limit": 20}
        assert _compute_action_config_hash(base) == _compute_action_config_hash(changed)

    def test_guard_string_normalized_to_dict(self):
        """Guard as string should produce same hash as equivalent dict."""
        string_guard = {"prompt": "X", "guard": "a > 1"}
        dict_guard = {"prompt": "X", "guard": {"clause": "a > 1", "behavior": "skip"}}
        assert _compute_action_config_hash(string_guard) == _compute_action_config_hash(dict_guard)

    def test_guard_none_handled(self):
        """guard: null should not crash."""
        config = {"prompt": "X", "guard": None}
        h = _compute_action_config_hash(config)
        assert isinstance(h, str) and len(h) == 16

    def test_missing_fields_produce_stable_hash(self):
        """Config with no prompt/model/schema/guard should still hash."""
        config = {}
        h = _compute_action_config_hash(config)
        assert isinstance(h, str) and len(h) == 16

    def test_hash_is_16_hex_chars(self):
        config = {"prompt": "X", "model": "m"}
        h = _compute_action_config_hash(config)
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)


class TestConfigChangeInvalidation:
    """_maybe_invalidate_completed_status must detect config hash changes."""

    def _make_executor(self, state_mgr):
        action_runner = MagicMock()
        action_runner.storage_backend = MagicMock()
        deps = ExecutorDependencies(
            action_runner=action_runner,
            state_manager=state_mgr,
            skip_evaluator=MagicMock(),
            batch_manager=MagicMock(),
            output_manager=MagicMock(),
        )
        return ActionExecutor(deps)

    def test_config_change_resets_to_pending(self, tmp_path):
        """Changed model triggers invalidation when stored hash exists."""
        status_file = tmp_path / "status.json"
        state_mgr = ActionStateManager(status_file, ["action_a"])

        old_config = {"prompt": "X", "model": "gpt-4", "record_limit": 10}
        old_hash = _compute_action_config_hash(old_config)
        state_mgr.update_status(
            "action_a", ActionStatus.COMPLETED, record_limit=10, config_hash=old_hash
        )

        new_config = {"prompt": "X", "model": "gpt-4o", "record_limit": 10}
        executor = self._make_executor(state_mgr)
        result = executor._maybe_invalidate_completed_status(
            "action_a", new_config, ActionStatus.COMPLETED
        )
        assert result == ActionStatus.PENDING

    def test_same_config_stays_completed(self, tmp_path):
        """Identical config should not invalidate."""
        status_file = tmp_path / "status.json"
        state_mgr = ActionStateManager(status_file, ["action_a"])

        config = {"prompt": "X", "model": "gpt-4", "record_limit": 10}
        config_hash = _compute_action_config_hash(config)
        state_mgr.update_status(
            "action_a", ActionStatus.COMPLETED, record_limit=10, config_hash=config_hash
        )

        executor = self._make_executor(state_mgr)
        result = executor._maybe_invalidate_completed_status(
            "action_a", config, ActionStatus.COMPLETED
        )
        assert result == ActionStatus.COMPLETED

    def test_missing_stored_hash_does_not_invalidate(self, tmp_path):
        """First run or upgrade -- no stored hash means no invalidation."""
        status_file = tmp_path / "status.json"
        state_mgr = ActionStateManager(status_file, ["action_a"])
        state_mgr.update_status("action_a", ActionStatus.COMPLETED, record_limit=10)

        config = {"prompt": "X", "model": "gpt-4", "record_limit": 10}
        executor = self._make_executor(state_mgr)
        result = executor._maybe_invalidate_completed_status(
            "action_a", config, ActionStatus.COMPLETED
        )
        assert result == ActionStatus.COMPLETED

    def test_limit_change_still_invalidates(self, tmp_path):
        """Limit changes should still trigger invalidation (existing behavior)."""
        status_file = tmp_path / "status.json"
        state_mgr = ActionStateManager(status_file, ["action_a"])

        config_hash = _compute_action_config_hash({"prompt": "X", "model": "m"})
        state_mgr.update_status(
            "action_a", ActionStatus.COMPLETED, record_limit=10, config_hash=config_hash
        )

        new_config = {"prompt": "X", "model": "m", "record_limit": 20}
        executor = self._make_executor(state_mgr)
        result = executor._maybe_invalidate_completed_status(
            "action_a", new_config, ActionStatus.COMPLETED
        )
        assert result == ActionStatus.PENDING

    def test_non_completed_status_not_checked(self, tmp_path):
        """PENDING/RUNNING actions should be returned as-is."""
        status_file = tmp_path / "status.json"
        state_mgr = ActionStateManager(status_file, ["action_a"])

        executor = self._make_executor(state_mgr)
        result = executor._maybe_invalidate_completed_status(
            "action_a", {"prompt": "X"}, ActionStatus.PENDING
        )
        assert result == ActionStatus.PENDING

    def test_clear_disposition_called_on_config_invalidation(self, tmp_path):
        """Dispositions must be cleared when config change triggers reset."""
        status_file = tmp_path / "status.json"
        state_mgr = ActionStateManager(status_file, ["action_a"])

        old_config = {"prompt": "X", "model": "gpt-4"}
        old_hash = _compute_action_config_hash(old_config)
        state_mgr.update_status(
            "action_a", ActionStatus.COMPLETED, record_limit=10, config_hash=old_hash
        )

        new_config = {"prompt": "X", "model": "gpt-4o", "record_limit": 10}
        executor = self._make_executor(state_mgr)
        executor._maybe_invalidate_completed_status("action_a", new_config, ActionStatus.COMPLETED)

        executor.deps.action_runner.storage_backend.clear_disposition.assert_called_once_with(
            "action_a"
        )


class TestCompletionMetadata:
    """_completion_metadata must include config_hash alongside limits."""

    def test_includes_config_hash(self):
        config = {"prompt": "X", "model": "m", "record_limit": 5, "file_limit": 10}
        meta = ActionExecutor._completion_metadata(config)
        assert "config_hash" in meta
        assert meta["config_hash"] == _compute_action_config_hash(config)
        assert meta["record_limit"] == 5
        assert meta["file_limit"] == 10
