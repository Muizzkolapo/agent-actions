"""Tests for graduated results tracking in RecoveryState."""

import json
import logging

import pytest

from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend.create(db_path=str(tmp_path / "test.db"), workflow_name="test")
    b.initialize()
    yield b
    b.close()


class TestRecoveryStateGraduatedFields:
    """Verify graduated_results and evaluation_strategy_name field behavior."""

    def test_new_state_has_expected_defaults(self):
        """New state defaults graduated_results to [] and evaluation_strategy_name to None."""
        state = RecoveryState(phase="retry")
        assert state.graduated_results == []
        assert state.evaluation_strategy_name is None

    def test_graduated_results_stores_dicts(self):
        """graduated_results stores plain dicts, not BatchResult objects."""
        records = [
            {"custom_id": "r1", "content": '{"field": "value1"}', "success": True},
            {"custom_id": "r2", "content": '{"field": "value2"}', "success": True},
        ]
        state = RecoveryState(phase="retry", graduated_results=records)
        assert state.graduated_results == records

    def test_evaluation_strategy_name_set(self):
        """evaluation_strategy_name can be set to a string."""
        state = RecoveryState(phase="repair", evaluation_strategy_name="validation")
        assert state.evaluation_strategy_name == "validation"

    def test_graduated_and_accumulated_are_separate(self):
        """graduated_results and accumulated_results are independent lists."""
        graduated = [{"custom_id": "g1"}]
        accumulated = [{"custom_id": "a1"}]
        state = RecoveryState(
            phase="retry",
            graduated_results=graduated,
            accumulated_results=accumulated,
        )
        state.graduated_results.append({"custom_id": "g2"})
        assert len(state.accumulated_results) == 1
        assert len(state.graduated_results) == 2

    def test_finalization_merge(self):
        """graduated + accumulated merge produces complete result set."""
        state = RecoveryState(
            phase="done",
            graduated_results=[
                {"custom_id": "r1", "content": "a", "success": True},
                {"custom_id": "r2", "content": "b", "success": True},
            ],
            accumulated_results=[
                {"custom_id": "r3", "content": "c", "success": True},
                {"custom_id": "r4", "content": "d", "success": False},
            ],
        )
        final = state.graduated_results + state.accumulated_results
        assert len(final) == 4
        ids = [r["custom_id"] for r in final]
        assert ids == ["r1", "r2", "r3", "r4"]


class TestRecoveryStateSerialization:
    """Verify JSON roundtrip for graduated fields via RecoveryStateManager."""

    def test_serialize_roundtrip_with_graduated(self, backend):
        """State with graduated results survives save/load roundtrip."""
        state = RecoveryState(
            phase="repair",
            graduated_results=[
                {"custom_id": "r1", "content": '{"x": 1}', "success": True},
                {"custom_id": "r2", "content": '{"x": 2}', "success": True},
            ],
            evaluation_strategy_name="validation",
        )
        RecoveryStateManager.save(backend, "test_action", "test_file", state)
        restored = RecoveryStateManager.load(backend, "test_action", "test_file")

        assert restored is not None
        assert restored.graduated_results == state.graduated_results
        assert restored.evaluation_strategy_name == "validation"
        assert restored.phase == "repair"

    def test_serialize_roundtrip_empty_graduated(self, backend):
        """State with default (empty) graduated fields roundtrips correctly."""
        state = RecoveryState(phase="retry", retry_attempt=2)
        RecoveryStateManager.save(backend, "test_action", "test_file", state)
        restored = RecoveryStateManager.load(backend, "test_action", "test_file")

        assert restored is not None
        assert restored.graduated_results == []
        assert restored.evaluation_strategy_name is None
        assert restored.retry_attempt == 2

    def test_deserialize_old_state_without_graduated(self, backend):
        """Old checkpoint data without graduated fields loads with defaults."""
        old_data = {
            "phase": "retry",
            "retry_attempt": 1,
            "retry_max_attempts": 3,
            "missing_ids": ["rec_001"],
            "record_failure_counts": {"rec_001": 1},
            "on_exhausted": "return_last",
            "accumulated_results": [{"custom_id": "r1", "content": "x", "success": True}],
        }
        # Write raw JSON directly to the metadata store, simulating an old-format state
        key = RecoveryStateManager._metadata_key("test_action", "test_file")
        backend.save_metadata(key, json.dumps(old_data))

        state = RecoveryStateManager.load(backend, "test_action", "test_file")

        assert state is not None
        assert state.graduated_results == []
        assert state.evaluation_strategy_name is None
        assert state.accumulated_results == [{"custom_id": "r1", "content": "x", "success": True}]
        assert state.missing_ids == ["rec_001"]

    def test_graduated_results_json_serializable(self, backend):
        """graduated_results content is plain JSON — no special types."""
        state = RecoveryState(
            phase="done",
            graduated_results=[
                {
                    "custom_id": "r1",
                    "content": '{"nested": {"key": "val"}}',
                    "success": True,
                    "metadata": {"source": "batch_001"},
                },
            ],
        )
        RecoveryStateManager.save(backend, "test_action", "test_file", state)

        # Read raw metadata and verify JSON structure
        key = RecoveryStateManager._metadata_key("test_action", "test_file")
        raw = json.loads(backend.load_metadata(key))

        assert raw["graduated_results"] == state.graduated_results
        assert raw["evaluation_strategy_name"] is None


class TestRecoveryStateManagerIntegration:
    """Verify RecoveryStateManager CRUD operations work with graduated fields."""

    def test_save_load_delete_cycle(self, backend):
        """Full create-read-delete cycle with graduated results."""
        state = RecoveryState(
            phase="repair",
            graduated_results=[{"custom_id": "g1"}],
            accumulated_results=[{"custom_id": "a1"}],
            evaluation_strategy_name="critique",
        )
        RecoveryStateManager.save(backend, "test_action", "cycle_test", state)
        assert RecoveryStateManager.exists(backend, "test_action", "cycle_test")

        loaded = RecoveryStateManager.load(backend, "test_action", "cycle_test")
        assert loaded is not None
        assert loaded.graduated_results == [{"custom_id": "g1"}]
        assert loaded.evaluation_strategy_name == "critique"

        deleted = RecoveryStateManager.delete(backend, "test_action", "cycle_test")
        assert deleted is True
        assert not RecoveryStateManager.exists(backend, "test_action", "cycle_test")

    def test_load_nonexistent_returns_none(self, backend):
        """Loading missing state returns None, not an error."""
        assert RecoveryStateManager.load(backend, "test_action", "missing") is None

    def test_overwrite_preserves_graduated(self, backend):
        """Saving updated state overwrites previous graduated results."""
        state1 = RecoveryState(
            phase="repair",
            graduated_results=[{"custom_id": "g1"}],
        )
        RecoveryStateManager.save(backend, "test_action", "overwrite_test", state1)

        state2 = RecoveryState(
            phase="repair",
            graduated_results=[{"custom_id": "g1"}, {"custom_id": "g2"}],
            evaluation_strategy_name="validation",
        )
        RecoveryStateManager.save(backend, "test_action", "overwrite_test", state2)

        loaded = RecoveryStateManager.load(backend, "test_action", "overwrite_test")
        assert loaded is not None
        assert len(loaded.graduated_results) == 2
        assert loaded.evaluation_strategy_name == "validation"


class TestRecoveryStateCorruptionHandling:
    """Verify load() logs at error-level on corruption and returns None."""

    _LOGGER = "agent_actions"

    def test_corrupt_json_logs_error_and_returns_none(self, backend, caplog):
        """Truncated/invalid JSON logs at error-level, returns None."""
        # Write corrupt JSON directly to the metadata store
        key = RecoveryStateManager._metadata_key("test_action", "test_file")
        backend.save_metadata(key, '{"phase": "retry", "retry_at')

        with caplog.at_level(logging.ERROR, logger=self._LOGGER):
            result = RecoveryStateManager.load(backend, "test_action", "test_file")

        assert result is None
        assert any(
            "Corrupt recovery state" in r.message and r.levelno == logging.ERROR
            for r in caplog.records
        )

    def test_missing_key_returns_none_silently(self, backend, caplog):
        """Missing key (first run) returns None with no error log."""
        with caplog.at_level(logging.DEBUG, logger=self._LOGGER):
            result = RecoveryStateManager.load(backend, "test_action", "nonexistent")

        assert result is None
        assert not any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_invalid_enum_value_logs_error(self, backend, caplog):
        """Valid JSON with bad enum value triggers ValueError in __post_init__."""
        key = RecoveryStateManager._metadata_key("test_action", "test_file")
        backend.save_metadata(
            key,
            json.dumps({"phase": "not_a_real_phase", "retry_attempt": 0}),
        )

        with caplog.at_level(logging.ERROR, logger=self._LOGGER):
            result = RecoveryStateManager.load(backend, "test_action", "test_file")

        assert result is None
        assert any(
            "Corrupt recovery state" in r.message and r.levelno == logging.ERROR
            for r in caplog.records
        )

    def test_valid_state_loads_without_error(self, backend, caplog):
        """Valid recovery state loads normally, no error logs."""
        state = RecoveryState(phase="retry", retry_attempt=1)
        RecoveryStateManager.save(backend, "test_action", "test_file", state)

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER):
            result = RecoveryStateManager.load(backend, "test_action", "test_file")

        assert result is not None
        assert result.retry_attempt == 1
        assert not any(r.levelno >= logging.WARNING for r in caplog.records)


class TestRecoveryStateLargeRoundtrip:
    """Verify large state roundtrips through the backend."""

    def test_large_state_serialization_roundtrip(self, backend):
        """200-record graduated state survives save/load roundtrip."""
        state = RecoveryState(
            phase="repair",
            graduated_results=[
                {"custom_id": f"rec_{i:04d}", "content": f'{{"v": {i}}}', "success": True}
                for i in range(200)
            ],
            evaluation_strategy_name="validation",
        )
        RecoveryStateManager.save(backend, "test_action", "large_test", state)
        loaded = RecoveryStateManager.load(backend, "test_action", "large_test")

        assert loaded is not None
        assert len(loaded.graduated_results) == 200
        assert loaded.graduated_results[0]["custom_id"] == "rec_0000"
        assert loaded.graduated_results[199]["custom_id"] == "rec_0199"
