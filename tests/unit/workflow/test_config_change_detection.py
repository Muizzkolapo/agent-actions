"""Tests for config change detection via action hash."""

from unittest.mock import MagicMock

import pytest

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
        action_runner.retried_records = frozenset()
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


class TestAResetActionCanSubmitItsBatchAgain:
    """A completed batch job is what stops a file being submitted twice. Left in place when
    the action is reset, it stops the reset action being submitted at all: the run reports
    the action complete with no records, over output the old configuration produced."""

    @staticmethod
    def _executor(state_mgr, backend):
        action_runner = MagicMock()
        action_runner.retried_records = frozenset()
        action_runner.storage_backend = backend
        deps = ExecutorDependencies(
            action_runner=action_runner,
            state_manager=state_mgr,
            skip_evaluator=MagicMock(),
            batch_manager=MagicMock(),
            output_manager=MagicMock(),
        )
        return ActionExecutor(deps)

    @staticmethod
    def _backend_with_a_finished_batch(tmp_path):
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        backend.initialize()
        keys = [
            f"{BatchRegistryManager.METADATA_KEY_PREFIX}action_a",
            "batch_context:action_a:page.json",
            "batch_inputs:action_a:page.json",
        ]
        for key in keys:
            backend.save_metadata(key, "{}")
        backend.save_metadata(f"{BatchRegistryManager.METADATA_KEY_PREFIX}other", "{}")
        return backend, keys

    @pytest.mark.parametrize(
        ("stored", "now"),
        [
            ({"prompt": "X", "model": "m", "record_limit": 1}, {"prompt": "X", "model": "m"}),
            ({"prompt": "X", "model": "m"}, {"prompt": "Y", "model": "m"}),
        ],
        ids=["the_record_limit_changed", "the_prompt_changed"],
    )
    def test_the_reset_clears_the_actions_batch_state(self, tmp_path, stored, now):
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

        backend, keys = self._backend_with_a_finished_batch(tmp_path)
        state_mgr = ActionStateManager(tmp_path / "status.json", ["action_a"])
        state_mgr.update_status(
            "action_a",
            ActionStatus.COMPLETED,
            record_limit=stored.get("record_limit"),
            config_hash=_compute_action_config_hash(stored),
        )

        status = self._executor(state_mgr, backend)._maybe_invalidate_completed_status(
            "action_a", now, ActionStatus.COMPLETED
        )

        assert status == ActionStatus.PENDING
        assert [backend.load_metadata(key) for key in keys] == [None, None, None]
        other = f"{BatchRegistryManager.METADATA_KEY_PREFIX}other"
        assert backend.load_metadata(other) == "{}", "another action's batch state was cleared"

    def test_an_action_that_is_not_reset_keeps_its_batch_state(self, tmp_path):
        backend, keys = self._backend_with_a_finished_batch(tmp_path)
        config = {"prompt": "X", "model": "m"}
        state_mgr = ActionStateManager(tmp_path / "status.json", ["action_a"])
        state_mgr.update_status(
            "action_a", ActionStatus.COMPLETED, config_hash=_compute_action_config_hash(config)
        )

        status = self._executor(state_mgr, backend)._maybe_invalidate_completed_status(
            "action_a", config, ActionStatus.COMPLETED
        )

        assert status == ActionStatus.COMPLETED
        assert [backend.load_metadata(key) for key in keys] == ["{}", "{}", "{}"]


class TestAResetReachesEveryActionThatReadsWhatItWrites:
    """A reset action writes new output. What was computed from the old output is stale:
    left complete, it holds answers for records that are gone and none for the new ones."""

    PROMPT = {"prompt": "X", "model": "m"}
    CONFIGS = {
        "split": {**PROMPT},
        "define": {**PROMPT, "dependencies": ["split"]},
        "grade": {**PROMPT, "dependencies": ["define"]},
        "aside": {**PROMPT},
    }

    def _workflow(self, tmp_path, configs=None, statuses=None):
        from agent_actions.storage.backend import DISPOSITION_SUCCESS
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        configs = configs or self.CONFIGS
        backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        backend.initialize()
        state_mgr = ActionStateManager(tmp_path / "status.json", list(configs))
        for name, config in configs.items():
            status = (statuses or {}).get(name, ActionStatus.COMPLETED)
            state_mgr.update_status(name, status, config_hash=_compute_action_config_hash(config))
            backend.set_disposition(name, "r1", DISPOSITION_SUCCESS)
            backend.save_metadata(f"batch_inputs:{name}:page.json", "[]")
        action_runner = MagicMock()
        action_runner.retried_records = frozenset()
        action_runner.storage_backend = backend
        action_runner.action_configs = configs
        executor = ActionExecutor(
            ExecutorDependencies(
                action_runner=action_runner,
                state_manager=state_mgr,
                skip_evaluator=MagicMock(),
                batch_manager=MagicMock(),
                output_manager=MagicMock(),
            )
        )
        return executor, state_mgr, backend

    @staticmethod
    def _reset(executor, name, configs):
        changed = {**configs[name], "prompt": "Y"}
        return executor._maybe_invalidate_completed_status(name, changed, ActionStatus.COMPLETED)

    def test_everything_below_it_is_reset_and_nothing_beside_it(self, tmp_path):
        executor, state_mgr, _ = self._workflow(tmp_path)

        self._reset(executor, "split", self.CONFIGS)

        assert {name: state_mgr.get_status(name) for name in self.CONFIGS} == {
            "split": ActionStatus.PENDING,
            "define": ActionStatus.PENDING,
            "grade": ActionStatus.PENDING,
            "aside": ActionStatus.COMPLETED,
        }

    def test_what_they_called_done_is_forgotten_with_them(self, tmp_path):
        """Reset alone, a dependent would carry its old answers past the gate (#1213)."""
        executor, _, backend = self._workflow(tmp_path)

        self._reset(executor, "split", self.CONFIGS)

        held = {name: len(backend.get_disposition(name)) for name in self.CONFIGS}
        assert held == {"split": 0, "define": 0, "grade": 0, "aside": 1}
        recorded = {
            name: backend.load_metadata(f"batch_inputs:{name}:page.json") for name in self.CONFIGS
        }
        assert recorded == {"split": None, "define": None, "grade": None, "aside": "[]"}

    def test_a_reset_in_the_middle_leaves_what_is_above_it(self, tmp_path):
        executor, state_mgr, _ = self._workflow(tmp_path)

        self._reset(executor, "define", self.CONFIGS)

        assert state_mgr.get_status("split") == ActionStatus.COMPLETED
        assert state_mgr.get_status("grade") == ActionStatus.PENDING

    def test_an_action_that_is_not_reset_resets_nothing_below_it(self, tmp_path):
        executor, state_mgr, _ = self._workflow(tmp_path)

        status = executor._maybe_invalidate_completed_status(
            "split", self.CONFIGS["split"], ActionStatus.COMPLETED
        )

        assert status == ActionStatus.COMPLETED
        assert state_mgr.get_status("define") == ActionStatus.COMPLETED

    @pytest.mark.parametrize(
        "left_as",
        [
            ActionStatus.COMPLETED_WITH_FAILURES,
            ActionStatus.BATCH_SUBMITTED,
            ActionStatus.CHECKING_BATCH,
            ActionStatus.PENDING,
            ActionStatus.FAILED,
        ],
    )
    def test_a_dependent_is_reset_whatever_state_it_was_left_in(self, tmp_path, left_as):
        """A batch still out was sent the old output, and the records an interrupted
        run had finished were answered from it. Left alone they complete as they are."""
        executor, state_mgr, backend = self._workflow(tmp_path, statuses={"define": left_as})

        self._reset(executor, "split", self.CONFIGS)

        assert state_mgr.get_status("define") == ActionStatus.PENDING
        assert backend.get_disposition("define") == []
        assert backend.load_metadata("batch_inputs:define:page.json") is None
        assert state_mgr.get_status("grade") == ActionStatus.PENDING

    def test_a_dependent_halted_on_exhaustion_is_no_longer_halted(self, tmp_path):
        """What it exhausted on is gone with the output it was read from."""
        from agent_actions.record.reasons import HALTED_ON_EXHAUSTED
        from agent_actions.storage.backend import DISPOSITION_FAILED, NODE_LEVEL_RECORD_ID
        from agent_actions.workflow.executor import action_is_halted

        executor, state_mgr, backend = self._workflow(
            tmp_path, statuses={"define": ActionStatus.FAILED}
        )
        backend.set_disposition(
            "define", NODE_LEVEL_RECORD_ID, DISPOSITION_FAILED, detail=HALTED_ON_EXHAUSTED
        )
        assert action_is_halted(backend, "define")

        self._reset(executor, "split", self.CONFIGS)

        assert not action_is_halted(backend, "define")
        assert state_mgr.get_status("define") == ActionStatus.PENDING

    def test_an_action_that_names_it_only_in_its_context_scope_is_reset(self, tmp_path):
        """It is handed that output through the record, and the run order counts it."""
        configs = {
            **self.CONFIGS,
            "reader": {
                **self.PROMPT,
                "dependencies": ["aside"],
                "context_scope": {"observe": ["aside.*", "split.topic"]},
            },
        }
        executor, state_mgr, _ = self._workflow(tmp_path, configs)

        self._reset(executor, "split", configs)

        assert state_mgr.get_status("reader") == ActionStatus.PENDING
        assert state_mgr.get_status("aside") == ActionStatus.COMPLETED

    def test_a_repair_resets_nothing(self, tmp_path):
        """It answers only the records it named. A reset would clear every other
        record's disposition, a failure among them, with nothing run to replace it."""
        executor, state_mgr, backend = self._workflow(tmp_path)
        executor.deps.action_runner.retried_records = frozenset({"r9"})

        status = self._reset(executor, "split", self.CONFIGS)

        assert status == ActionStatus.COMPLETED
        assert {name: state_mgr.get_status(name) for name in self.CONFIGS} == dict.fromkeys(
            self.CONFIGS, ActionStatus.COMPLETED
        )
        assert {name: len(backend.get_disposition(name)) for name in self.CONFIGS} == dict.fromkeys(
            self.CONFIGS, 1
        )

    def test_a_repair_that_finds_output_gone_leaves_the_readers_as_they_are(self, tmp_path):
        executor, state_mgr, backend = self._workflow(tmp_path)
        executor.deps.action_runner.retried_records = frozenset({"r9"})

        assert executor.verify_completion_status("split") is False

        assert state_mgr.get_status("define") == ActionStatus.COMPLETED
        assert len(backend.get_disposition("define")) == 1

    def test_the_readers_are_reset_before_the_action_itself(self, tmp_path):
        """A process killed part-way must leave the action as it was found, so the
        next run finds the same reason to reset it and reaches the readers again."""
        executor, state_mgr, backend = self._workflow(tmp_path)
        clear = backend.clear_disposition

        def killed_at_split(action_name, *args, **kwargs):
            if action_name == "split":
                raise RuntimeError("killed")
            return clear(action_name, *args, **kwargs)

        backend.clear_disposition = killed_at_split

        with pytest.raises(RuntimeError, match="killed"):
            self._reset(executor, "split", self.CONFIGS)

        assert state_mgr.get_status("split") == ActionStatus.COMPLETED
        assert state_mgr.get_status("define") == ActionStatus.PENDING
        assert state_mgr.get_status("grade") == ActionStatus.PENDING

    def test_the_order_the_configs_are_held_in_does_not_matter(self, tmp_path):
        configs = dict(reversed(list(self.CONFIGS.items())))
        executor, state_mgr, _ = self._workflow(tmp_path, configs)

        self._reset(executor, "split", configs)

        assert state_mgr.get_status("define") == ActionStatus.PENDING
        assert state_mgr.get_status("grade") == ActionStatus.PENDING
        assert state_mgr.get_status("aside") == ActionStatus.COMPLETED

    def test_an_action_run_again_because_its_output_is_gone_takes_them_with_it(self, tmp_path):
        """It will write new output all the same, and theirs was computed from the old."""
        executor, state_mgr, backend = self._workflow(tmp_path)
        for name in ("define", "grade", "aside"):
            backend.write_target(name, "page.json", [{"source_guid": "r1", "content": {}}])

        should_skip = executor.verify_completion_status("split")

        assert should_skip is False
        assert {name: state_mgr.get_status(name) for name in self.CONFIGS} == {
            "split": ActionStatus.PENDING,
            "define": ActionStatus.PENDING,
            "grade": ActionStatus.PENDING,
            "aside": ActionStatus.COMPLETED,
        }

    def test_an_action_run_again_over_a_failure_it_recorded_takes_them_with_it(self, tmp_path):
        from agent_actions.storage.backend import DISPOSITION_FAILED, NODE_LEVEL_RECORD_ID

        executor, state_mgr, backend = self._workflow(tmp_path)
        backend.write_target("split", "page.json", [{"source_guid": "r1", "content": {}}])
        backend.set_disposition("split", NODE_LEVEL_RECORD_ID, DISPOSITION_FAILED)

        assert executor.verify_completion_status("split") is False

        assert state_mgr.get_status("split") == ActionStatus.PENDING
        assert state_mgr.get_status("define") == ActionStatus.PENDING
        assert state_mgr.get_status("grade") == ActionStatus.PENDING
        assert state_mgr.get_status("aside") == ActionStatus.COMPLETED

    def test_an_action_run_again_because_its_output_could_not_be_read_takes_them_with_it(
        self, tmp_path
    ):
        executor, state_mgr, backend = self._workflow(tmp_path)
        backend.list_target_files = MagicMock(side_effect=RuntimeError("unreadable"))

        assert executor.verify_completion_status("split") is False

        assert state_mgr.get_status("split") == ActionStatus.PENDING
        assert state_mgr.get_status("define") == ActionStatus.PENDING

    def test_a_reset_that_fails_part_way_is_not_read_as_a_failure_to_verify(self, tmp_path):
        """Swallowed, the run goes on with some readers reset and the rest left stale."""
        executor, state_mgr, backend = self._workflow(tmp_path)
        clear = backend.clear_disposition

        def fails_at_grade(action_name, *args, **kwargs):
            if action_name == "grade":
                raise RuntimeError("store went away")
            return clear(action_name, *args, **kwargs)

        backend.clear_disposition = fails_at_grade

        with pytest.raises(RuntimeError, match="store went away"):
            executor.verify_completion_status("split")

        assert state_mgr.get_status("split") == ActionStatus.COMPLETED

    def test_an_action_that_merges_versions_follows_any_one_of_them(self, tmp_path):
        configs = {
            "vote_1": {**self.PROMPT},
            "vote_2": {**self.PROMPT},
            "tally": {**self.PROMPT, "version_consumption_config": {"source": "vote"}},
        }
        executor, state_mgr, _ = self._workflow(tmp_path, configs)

        self._reset(executor, "vote_2", configs)

        assert state_mgr.get_status("tally") == ActionStatus.PENDING
        assert state_mgr.get_status("vote_1") == ActionStatus.COMPLETED


def _executor_for_stamp():
    action_runner = MagicMock()
    action_runner.retried_records = frozenset()
    return ActionExecutor(
        ExecutorDependencies(
            action_runner=action_runner,
            state_manager=MagicMock(),
            skip_evaluator=MagicMock(),
            batch_manager=MagicMock(),
            output_manager=MagicMock(),
        )
    )


class TestCompletionMetadata:
    """_completion_metadata must include config_hash alongside limits."""

    def test_includes_config_hash(self):
        config = {"prompt": "X", "model": "m", "record_limit": 5, "file_limit": 10}
        meta = _executor_for_stamp()._completion_metadata("action_a", config)
        assert "config_hash" in meta
        assert meta["config_hash"] == _compute_action_config_hash(config)
        assert meta["record_limit"] == 5
        assert meta["file_limit"] == 10
