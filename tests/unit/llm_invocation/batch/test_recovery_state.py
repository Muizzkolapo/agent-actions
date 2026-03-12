"""Tests for RecoveryState persistence (RecoveryStateManager).

Covers:
- Save and load round-trip
- Load returns None for missing file
- Delete removes file
- Exists check
- Corrupt file handling
"""

from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)


class TestRecoveryStateSaveAndLoad:
    """Tests for save/load round-trip."""

    def test_save_and_load_round_trip(self, tmp_path):
        """Should persist state and reload it identically."""
        output_dir = str(tmp_path)
        # Ensure batch/ subdir exists for the manager
        (tmp_path / "batch").mkdir()

        state = RecoveryState(
            phase="retry",
            retry_attempt=2,
            retry_max_attempts=3,
            missing_ids=["a", "b"],
            record_failure_counts={"a": 2, "b": 1},
            accumulated_results=[{"custom_id": "c", "content": "ok", "success": True}],
        )

        RecoveryStateManager.save(output_dir, "test.json", state)
        loaded = RecoveryStateManager.load(output_dir, "test.json")

        assert loaded is not None
        assert loaded.phase == "retry"
        assert loaded.retry_attempt == 2
        assert loaded.retry_max_attempts == 3
        assert loaded.missing_ids == ["a", "b"]
        assert loaded.record_failure_counts == {"a": 2, "b": 1}
        assert len(loaded.accumulated_results) == 1
        assert loaded.accumulated_results[0]["custom_id"] == "c"

    def test_save_and_load_reprompt_state(self, tmp_path):
        """Should persist reprompt-specific fields."""
        output_dir = str(tmp_path)
        (tmp_path / "batch").mkdir()

        state = RecoveryState(
            phase="reprompt",
            reprompt_attempt=1,
            reprompt_max_attempts=2,
            validation_name="check_json",
            reprompt_attempts_per_record={"x": 1},
            validation_status={"x": False},
            on_exhausted="raise",
        )

        RecoveryStateManager.save(output_dir, "test.json", state)
        loaded = RecoveryStateManager.load(output_dir, "test.json")

        assert loaded is not None
        assert loaded.phase == "reprompt"
        assert loaded.reprompt_attempt == 1
        assert loaded.validation_name == "check_json"
        assert loaded.reprompt_attempts_per_record == {"x": 1}
        assert loaded.on_exhausted == "raise"

    def test_save_creates_directory(self, tmp_path):
        """Should create batch/ directory if it doesn't exist."""
        output_dir = str(tmp_path)
        state = RecoveryState(phase="retry")

        path = RecoveryStateManager.save(output_dir, "test.json", state)

        assert path.exists()
        assert "batch" in str(path)


class TestRecoveryStateLoad:
    """Tests for load edge cases."""

    def test_load_returns_none_for_missing_file(self, tmp_path):
        """Should return None when state file doesn't exist."""
        result = RecoveryStateManager.load(str(tmp_path), "nonexistent.json")
        assert result is None

    def test_load_returns_none_for_corrupt_json(self, tmp_path):
        """Should return None for corrupt JSON."""
        (tmp_path / "batch").mkdir()
        state_file = tmp_path / "batch" / ".recovery_state_test.json.json"
        state_file.write_text("not valid json{{{")

        result = RecoveryStateManager.load(str(tmp_path), "test.json")
        assert result is None


class TestRecoveryStateDelete:
    """Tests for delete."""

    def test_delete_existing_file(self, tmp_path):
        """Should delete file and return True."""
        output_dir = str(tmp_path)
        (tmp_path / "batch").mkdir()

        state = RecoveryState(phase="retry")
        RecoveryStateManager.save(output_dir, "test.json", state)

        assert RecoveryStateManager.exists(output_dir, "test.json") is True
        result = RecoveryStateManager.delete(output_dir, "test.json")
        assert result is True
        assert RecoveryStateManager.exists(output_dir, "test.json") is False

    def test_delete_nonexistent_returns_false(self, tmp_path):
        """Should return False when file doesn't exist."""
        result = RecoveryStateManager.delete(str(tmp_path), "nope.json")
        assert result is False


class TestRecoveryStateExists:
    """Tests for exists check."""

    def test_exists_true_after_save(self, tmp_path):
        """Should return True after save."""
        output_dir = str(tmp_path)
        (tmp_path / "batch").mkdir()

        state = RecoveryState(phase="done")
        RecoveryStateManager.save(output_dir, "test.json", state)

        assert RecoveryStateManager.exists(output_dir, "test.json") is True

    def test_exists_false_before_save(self, tmp_path):
        """Should return False before any save."""
        assert RecoveryStateManager.exists(str(tmp_path), "test.json") is False
