"""Tests for graduated results tracking in RecoveryState."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)


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
        state = RecoveryState(phase="reprompt", evaluation_strategy_name="validation")
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

    def test_serialize_roundtrip_with_graduated(self, tmp_path):
        """State with graduated results survives save/load roundtrip."""
        state = RecoveryState(
            phase="reprompt",
            reprompt_attempt=1,
            graduated_results=[
                {"custom_id": "r1", "content": '{"x": 1}', "success": True},
                {"custom_id": "r2", "content": '{"x": 2}', "success": True},
            ],
            evaluation_strategy_name="validation",
        )
        RecoveryStateManager.save(str(tmp_path), "test_action", state)
        restored = RecoveryStateManager.load(str(tmp_path), "test_action")

        assert restored is not None
        assert restored.graduated_results == state.graduated_results
        assert restored.evaluation_strategy_name == "validation"
        assert restored.phase == "reprompt"
        assert restored.reprompt_attempt == 1

    def test_serialize_roundtrip_empty_graduated(self, tmp_path):
        """State with default (empty) graduated fields roundtrips correctly."""
        state = RecoveryState(phase="retry", retry_attempt=2)
        RecoveryStateManager.save(str(tmp_path), "test_action", state)
        restored = RecoveryStateManager.load(str(tmp_path), "test_action")

        assert restored is not None
        assert restored.graduated_results == []
        assert restored.evaluation_strategy_name is None
        assert restored.retry_attempt == 2

    def test_deserialize_old_state_without_graduated(self, tmp_path):
        """Old checkpoint files without graduated fields load with defaults."""
        old_data = {
            "phase": "retry",
            "retry_attempt": 1,
            "retry_max_attempts": 3,
            "missing_ids": ["rec_001"],
            "record_failure_counts": {"rec_001": 1},
            "reprompt_attempt": 0,
            "reprompt_max_attempts": 2,
            "validation_name": None,
            "reprompt_attempts_per_record": {},
            "validation_status": {},
            "on_exhausted": "return_last",
            "accumulated_results": [{"custom_id": "r1", "content": "x", "success": True}],
        }
        state_path = tmp_path / "batch" / ".recovery_state_test_action.json"
        state_path.parent.mkdir(parents=True)
        with open(state_path, "w") as f:
            json.dump(old_data, f)

        state = RecoveryStateManager.load(str(tmp_path), "test_action")

        assert state is not None
        assert state.graduated_results == []
        assert state.evaluation_strategy_name is None
        assert state.accumulated_results == [{"custom_id": "r1", "content": "x", "success": True}]
        assert state.missing_ids == ["rec_001"]

    def test_graduated_results_json_serializable(self, tmp_path):
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
        path = RecoveryStateManager.save(str(tmp_path), "test_action", state)
        with open(path) as f:
            raw = json.load(f)

        assert raw["graduated_results"] == state.graduated_results
        assert raw["evaluation_strategy_name"] is None


class TestRecoveryStateManagerIntegration:
    """Verify RecoveryStateManager CRUD operations work with graduated fields."""

    def test_save_load_delete_cycle(self, tmp_path):
        """Full create-read-delete cycle with graduated results."""
        state = RecoveryState(
            phase="reprompt",
            graduated_results=[{"custom_id": "g1"}],
            accumulated_results=[{"custom_id": "a1"}],
            evaluation_strategy_name="critique",
        )
        tmpdir = str(tmp_path)
        RecoveryStateManager.save(tmpdir, "cycle_test", state)
        assert RecoveryStateManager.exists(tmpdir, "cycle_test")

        loaded = RecoveryStateManager.load(tmpdir, "cycle_test")
        assert loaded is not None
        assert loaded.graduated_results == [{"custom_id": "g1"}]
        assert loaded.evaluation_strategy_name == "critique"

        deleted = RecoveryStateManager.delete(tmpdir, "cycle_test")
        assert deleted is True
        assert not RecoveryStateManager.exists(tmpdir, "cycle_test")

    def test_load_nonexistent_returns_none(self, tmp_path):
        """Loading missing state returns None, not an error."""
        assert RecoveryStateManager.load(str(tmp_path), "missing") is None

    def test_overwrite_preserves_graduated(self, tmp_path):
        """Saving updated state overwrites previous graduated results."""
        tmpdir = str(tmp_path)
        state1 = RecoveryState(
            phase="reprompt",
            graduated_results=[{"custom_id": "g1"}],
        )
        RecoveryStateManager.save(tmpdir, "overwrite_test", state1)

        state2 = RecoveryState(
            phase="reprompt",
            graduated_results=[{"custom_id": "g1"}, {"custom_id": "g2"}],
            evaluation_strategy_name="validation",
        )
        RecoveryStateManager.save(tmpdir, "overwrite_test", state2)

        loaded = RecoveryStateManager.load(tmpdir, "overwrite_test")
        assert loaded is not None
        assert len(loaded.graduated_results) == 2
        assert loaded.evaluation_strategy_name == "validation"


class TestRecoveryStateAtomicWrite:
    """Verify save() uses atomic writes to prevent crash corruption."""

    def test_save_writes_via_temp_file(self, tmp_path):
        """save() writes to a temp file first, then renames — observable mid-write."""
        state = RecoveryState(phase="retry", retry_attempt=1)
        captured_tmp = {}

        original_replace = Path.replace

        def spy_replace(self_path, target):
            # Temp file should exist with valid JSON before rename
            captured_tmp["path"] = self_path
            captured_tmp["existed"] = self_path.exists()
            if self_path.exists():
                captured_tmp["content"] = json.loads(self_path.read_text())
            return original_replace(self_path, target)

        with patch.object(Path, "replace", spy_replace):
            path = RecoveryStateManager.save(str(tmp_path), "atomic_test", state)

        # Temp file was observed with valid data before rename
        assert captured_tmp["existed"] is True
        assert captured_tmp["content"]["phase"] == "retry"
        assert str(captured_tmp["path"]).endswith(".json.tmp")

        # Final file is correct, temp file gone
        assert path.exists()
        assert not captured_tmp["path"].exists()

    def test_original_file_survives_write_error(self, tmp_path):
        """If save() fails mid-write, the previous state file is untouched."""
        tmpdir = str(tmp_path)

        # Save initial good state
        state_v1 = RecoveryState(
            phase="retry",
            graduated_results=[{"custom_id": "r1"}],
        )
        path = RecoveryStateManager.save(tmpdir, "crash_test", state_v1)

        # Record original content
        original_content = path.read_text()

        # Attempt a second save that fails during json.dump
        state_v2 = RecoveryState(
            phase="reprompt",
            graduated_results=[{"custom_id": "r1"}, {"custom_id": "r2"}],
        )
        with (
            patch(
                "agent_actions.llm.batch.infrastructure.recovery_state.json.dump",
                side_effect=OSError("disk full"),
            ),
            pytest.raises(OSError),
        ):
            RecoveryStateManager.save(tmpdir, "crash_test", state_v2)

        # Original file is still intact
        assert path.read_text() == original_content
        loaded = RecoveryStateManager.load(tmpdir, "crash_test")
        assert loaded is not None
        assert loaded.phase == "retry"
        assert len(loaded.graduated_results) == 1

        # No leftover temp file
        tmp_file = path.with_suffix(".json.tmp")
        assert not tmp_file.exists()

    def test_save_error_cleans_up_temp_file(self, tmp_path):
        """On write failure, the temp file is removed — no disk litter."""
        state = RecoveryState(phase="retry")
        with patch(
            "agent_actions.llm.batch.infrastructure.recovery_state.json.dump",
            side_effect=OSError("disk full"),
        ):
            try:
                RecoveryStateManager.save(str(tmp_path), "cleanup_test", state)
            except OSError:
                pass

        # No temp file left behind
        batch_dir = tmp_path / "batch"
        assert batch_dir.exists()
        assert list(batch_dir.glob("*.tmp")) == []

    def test_rename_failure_cleans_up_and_preserves_original(self, tmp_path):
        """If rename fails after successful write, temp is cleaned up and original survives."""
        tmpdir = str(tmp_path)

        # Save initial good state
        state_v1 = RecoveryState(
            phase="retry",
            graduated_results=[{"custom_id": "r1"}],
        )
        path = RecoveryStateManager.save(tmpdir, "rename_test", state_v1)
        original_content = path.read_text()

        # Attempt a second save where rename fails
        state_v2 = RecoveryState(phase="reprompt")
        with (
            patch.object(Path, "replace", side_effect=OSError("cross-device link")),
            pytest.raises(OSError),
        ):
            RecoveryStateManager.save(tmpdir, "rename_test", state_v2)

        # Original file is untouched
        assert path.read_text() == original_content
        loaded = RecoveryStateManager.load(tmpdir, "rename_test")
        assert loaded is not None
        assert loaded.phase == "retry"

        # Temp file cleaned up
        assert not path.with_suffix(".json.tmp").exists()

    def test_save_error_raises_oserror(self, tmp_path):
        """save() wraps write failures in OSError with context."""
        state = RecoveryState(phase="retry")
        with patch(
            "agent_actions.llm.batch.infrastructure.recovery_state.json.dump",
            side_effect=ValueError("bad data"),
        ):
            with pytest.raises(OSError, match="Failed to save recovery state"):
                RecoveryStateManager.save(str(tmp_path), "error_test", state)

    def test_large_state_serialization_roundtrip(self, tmp_path):
        """200-record graduated state survives save/load roundtrip."""
        state = RecoveryState(
            phase="reprompt",
            reprompt_attempt=1,
            graduated_results=[
                {"custom_id": f"rec_{i:04d}", "content": f'{{"v": {i}}}', "success": True}
                for i in range(200)
            ],
            evaluation_strategy_name="validation",
        )
        RecoveryStateManager.save(str(tmp_path), "large_test", state)
        loaded = RecoveryStateManager.load(str(tmp_path), "large_test")

        assert loaded is not None
        assert len(loaded.graduated_results) == 200
        assert loaded.graduated_results[0]["custom_id"] == "rec_0000"
        assert loaded.graduated_results[199]["custom_id"] == "rec_0199"
