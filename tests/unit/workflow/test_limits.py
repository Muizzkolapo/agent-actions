"""Tests for record_limit and file_limit feature.

Covers:
- record_limit slicing in process_initial_stage
- file_limit early break in all 3 file-walking paths
- Status invalidation when limits change between runs
- Edge cases: limit > total records, limit = total, None (no-op)
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus
from agent_actions.workflow.runner_file_processing import (
    _file_limit_reached,
    process_directory_files,
    process_merged_files,
)

# ── _file_limit_reached helper ────────────────────────────────────────


class TestFileLimitReached:
    def test_none_means_no_limit(self):
        assert _file_limit_reached({}, 100, "act") is False

    def test_below_limit(self):
        assert _file_limit_reached({"file_limit": 5}, 3, "act") is False

    def test_at_limit(self):
        assert _file_limit_reached({"file_limit": 5}, 5, "act") is True

    def test_above_limit(self):
        assert _file_limit_reached({"file_limit": 5}, 10, "act") is True


# ── file_limit in process_directory_files ─────────────────────────────


class TestFileLimitDirectoryFiles:
    def _setup_files(self, tmp_path, count):
        """Create count JSON files in tmp_path."""
        for i in range(count):
            (tmp_path / f"file_{i:03d}.json").write_text(json.dumps([{"id": i}]))

    def test_file_limit_caps_files_processed(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        self._setup_files(input_dir, 5)
        output = tmp_path / "output"
        output.mkdir()

        runner = MagicMock()
        runner._should_skip_item.return_value = False

        params = MagicMock()
        params.action_config = {"file_limit": 2}
        params.action_name = "test"
        params.strategy = MagicMock()
        params.idx = 0
        params.file_type_filter = None

        count = process_directory_files(runner, input_dir, output, str(input_dir), params, set())
        assert count == 2
        assert runner._process_single_file.call_count == 2

    def test_no_file_limit_processes_all(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        self._setup_files(input_dir, 5)
        output = tmp_path / "output"
        output.mkdir()

        runner = MagicMock()
        runner._should_skip_item.return_value = False

        params = MagicMock()
        params.action_config = {}
        params.action_name = "test"
        params.strategy = MagicMock()
        params.idx = 0
        params.file_type_filter = None

        count = process_directory_files(runner, input_dir, output, str(input_dir), params, set())
        assert count == 5

    def test_file_limit_greater_than_total(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        self._setup_files(input_dir, 3)
        output = tmp_path / "output"
        output.mkdir()

        runner = MagicMock()
        runner._should_skip_item.return_value = False

        params = MagicMock()
        params.action_config = {"file_limit": 100}
        params.action_name = "test"
        params.strategy = MagicMock()
        params.idx = 0
        params.file_type_filter = None

        count = process_directory_files(runner, input_dir, output, str(input_dir), params, set())
        assert count == 3


# ── file_limit in process_merged_files ────────────────────────────────


class TestFileLimitMergedFiles:
    def test_file_limit_caps_merged_groups(self, tmp_path):
        upstream = tmp_path / "upstream"
        output = tmp_path / "output"
        upstream.mkdir()
        output.mkdir()

        # Create 4 files
        for i in range(4):
            (upstream / f"file_{i}.json").write_text(json.dumps([{"id": i}]))

        runner = MagicMock()
        runner._collect_files_from_upstream.return_value = {
            Path(f"file_{i}.json"): [upstream / f"file_{i}.json"] for i in range(4)
        }

        params = MagicMock()
        params.upstream_data_dirs = [str(upstream)]
        params.output_directory = str(output)
        params.action_config = {"file_limit": 2}
        params.action_name = "test"
        params.strategy = MagicMock()
        params.idx = 0

        count = process_merged_files(runner, params)
        assert count == 2
        assert runner._process_single_file.call_count == 2


# ── record_limit in process_initial_stage ─────────────────────────────


class TestRecordLimitInitialStage:
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._save_source_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._validate_staged_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._prepare_online_data")
    @patch("agent_actions.input.loaders.file_reader.FileReader")
    @patch(
        "agent_actions.input.preprocessing.staging.initial_pipeline"
        "._process_online_mode_with_record_processor"
    )
    def test_record_limit_slices_data_before_source_save(
        self, mock_process, mock_reader, mock_prep, mock_validate, mock_save
    ):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )

        all_records = [{"id": i} for i in range(50)]
        all_src = [{"source_guid": f"guid_{i}", "content": str(i)} for i in range(50)]
        mock_prep.return_value = (all_records, all_src)

        reader_instance = MagicMock()
        reader_instance.read.return_value = "raw"
        reader_instance.file_type = ".json"
        mock_reader.return_value = reader_instance

        mock_process.return_value = "/output/file.json"

        ctx = InitialStageContext(
            agent_config={"record_limit": 10, "run_mode": "online"},
            agent_name="test",
            file_path="/input/data.json",
            base_directory="/input",
            output_directory="/output",
            storage_backend=MagicMock(),
        )

        process_initial_stage(ctx)

        # Source save should receive only 10 records (sliced BEFORE save)
        save_args = mock_save.call_args
        saved_src = save_args[0][0]  # first positional arg = src_text
        saved_data = save_args[0][1]  # second positional arg = data_chunk
        assert len(saved_data) == 10
        assert len(saved_src) == 10

        # Processing should also receive 10 records
        process_args = mock_process.call_args
        processed_data = process_args[0][0]  # first positional arg = data_chunk
        assert len(processed_data) == 10

    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._save_source_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._validate_staged_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._prepare_online_data")
    @patch("agent_actions.input.loaders.file_reader.FileReader")
    @patch(
        "agent_actions.input.preprocessing.staging.initial_pipeline"
        "._process_online_mode_with_record_processor"
    )
    def test_record_limit_none_passes_all(
        self, mock_process, mock_reader, mock_prep, mock_validate, mock_save
    ):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )

        all_records = [{"id": i} for i in range(50)]
        mock_prep.return_value = (all_records, [])

        reader_instance = MagicMock()
        reader_instance.read.return_value = "raw"
        reader_instance.file_type = ".json"
        mock_reader.return_value = reader_instance

        mock_process.return_value = "/output/file.json"

        ctx = InitialStageContext(
            agent_config={"run_mode": "online"},
            agent_name="test",
            file_path="/input/data.json",
            base_directory="/input",
            output_directory="/output",
            storage_backend=MagicMock(),
        )

        process_initial_stage(ctx)

        save_args = mock_save.call_args
        saved_data = save_args[0][1]
        assert len(saved_data) == 50

    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._save_source_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._validate_staged_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._prepare_online_data")
    @patch("agent_actions.input.loaders.file_reader.FileReader")
    @patch(
        "agent_actions.input.preprocessing.staging.initial_pipeline"
        "._process_online_mode_with_record_processor"
    )
    def test_record_limit_greater_than_total_is_noop(
        self, mock_process, mock_reader, mock_prep, mock_validate, mock_save
    ):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )

        all_records = [{"id": i} for i in range(5)]
        mock_prep.return_value = (all_records, [])

        reader_instance = MagicMock()
        reader_instance.read.return_value = "raw"
        reader_instance.file_type = ".json"
        mock_reader.return_value = reader_instance

        mock_process.return_value = "/output/file.json"

        ctx = InitialStageContext(
            agent_config={"record_limit": 100, "run_mode": "online"},
            agent_name="test",
            file_path="/input/data.json",
            base_directory="/input",
            output_directory="/output",
            storage_backend=MagicMock(),
        )

        process_initial_stage(ctx)

        save_args = mock_save.call_args
        saved_data = save_args[0][1]
        assert len(saved_data) == 5


# ── Status invalidation when limits change ────────────────────────────


class TestLimitStatusInvalidation:
    @pytest.fixture
    def mock_deps(self):
        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = MagicMock(spec=ActionStateManager)
        deps.action_runner = MagicMock()
        deps.action_runner.workflow_name = "test"
        deps.action_runner.get_action_folder.return_value = "/tmp/io"
        deps.action_runner.execution_order = ["act_a"]
        deps.skip_evaluator = MagicMock()
        deps.output_manager = MagicMock()
        deps.batch_manager = MagicMock()
        return deps

    @pytest.fixture
    def executor(self, mock_deps):
        return ActionExecutor(mock_deps)

    def test_limits_changed_resets_to_pending(self, executor, mock_deps):
        """Action completed with limit=10, re-run with limit=None should re-execute."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 10,
            "file_limit": None,
        }
        # Config now has no limit
        action_config = {"record_limit": None, "file_limit": None}
        mock_deps.skip_evaluator.should_skip_action.return_value = False

        mock_deps.action_runner.run_action.return_value = ("/out", None)
        executor.execute_action_sync(
            "act_a", action_idx=0, action_config=action_config, is_last_action=True
        )

        # Should have reset to pending, then run the action
        update_calls = mock_deps.state_manager.update_status.call_args_list
        assert update_calls[0] == (("act_a", ActionStatus.PENDING),)

    def test_same_limits_skips_action(self, executor, mock_deps):
        """Action completed with same limits should be skipped."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 10,
            "file_limit": 2,
        }
        action_config = {"record_limit": 10, "file_limit": 2}

        storage = MagicMock()
        storage.list_target_files.return_value = ["file.json"]
        storage.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend = storage

        result = executor.execute_action_sync(
            "act_a", action_idx=0, action_config=action_config, is_last_action=False
        )

        assert result.success is True
        assert result.status == ActionStatus.COMPLETED
        mock_deps.action_runner.run_action.assert_not_called()

    def test_limits_changed_clears_dispositions(self, executor, mock_deps):
        """When limits change, stale dispositions must be cleared alongside status reset."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 10,
            "file_limit": None,
        }
        storage = MagicMock()
        mock_deps.action_runner.storage_backend = storage

        result = executor._maybe_invalidate_completed_status(
            "act_a", {"record_limit": 2, "file_limit": None}, ActionStatus.COMPLETED
        )

        assert result == ActionStatus.PENDING
        storage.clear_disposition.assert_called_once_with("act_a")

    def test_limits_unchanged_does_not_clear_dispositions(self, executor, mock_deps):
        """When limits are unchanged, dispositions are untouched."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 10,
            "file_limit": None,
        }
        storage = MagicMock()
        mock_deps.action_runner.storage_backend = storage

        result = executor._maybe_invalidate_completed_status(
            "act_a", {"record_limit": 10, "file_limit": None}, ActionStatus.COMPLETED
        )

        assert result == ActionStatus.COMPLETED
        storage.clear_disposition.assert_not_called()

    def test_limits_changed_no_storage_backend(self, executor, mock_deps):
        """When limits change but no storage backend, status resets without error."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {
            "status": ActionStatus.COMPLETED,
            "record_limit": 10,
            "file_limit": None,
        }
        mock_deps.action_runner.storage_backend = None

        result = executor._maybe_invalidate_completed_status(
            "act_a", {"record_limit": 2, "file_limit": None}, ActionStatus.COMPLETED
        )

        assert result == ActionStatus.PENDING

    def test_no_limits_old_status_no_invalidation(self, executor, mock_deps):
        """Old status file without limit keys + config with no limits = no invalidation."""
        mock_deps.state_manager.get_status.return_value = ActionStatus.COMPLETED
        mock_deps.state_manager.get_status_details.return_value = {"status": ActionStatus.COMPLETED}
        action_config = {}

        storage = MagicMock()
        storage.list_target_files.return_value = ["file.json"]
        storage.has_disposition.return_value = False
        mock_deps.action_runner.storage_backend = storage

        result = executor.execute_action_sync(
            "act_a", action_idx=0, action_config=action_config, is_last_action=False
        )

        assert result.success is True
        assert result.status == ActionStatus.COMPLETED
        mock_deps.action_runner.run_action.assert_not_called()


# ── Schema validation ─────────────────────────────────────────────────


class TestLimitSchemaValidation:
    def test_record_limit_rejects_zero(self):
        from pydantic import ValidationError

        from agent_actions.config.schema import ActionConfig

        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            ActionConfig(
                name="test",
                intent="test",
                record_limit=0,
            )

    def test_record_limit_rejects_negative(self):
        from pydantic import ValidationError

        from agent_actions.config.schema import ActionConfig

        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            ActionConfig(
                name="test",
                intent="test",
                record_limit=-5,
            )

    def test_file_limit_rejects_zero(self):
        from pydantic import ValidationError

        from agent_actions.config.schema import ActionConfig

        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            ActionConfig(
                name="test",
                intent="test",
                file_limit=0,
            )

    def test_limits_accept_none(self):
        from agent_actions.config.schema import ActionConfig

        config = ActionConfig(name="test", intent="test")
        assert config.record_limit is None
        assert config.file_limit is None

    def test_limits_accept_positive(self):
        from agent_actions.config.schema import ActionConfig

        config = ActionConfig(name="test", intent="test", record_limit=10, file_limit=5)
        assert config.record_limit == 10
        assert config.file_limit == 5
