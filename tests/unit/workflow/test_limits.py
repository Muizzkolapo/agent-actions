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


def _backend_holding_nothing():
    """A backend for an action with no stored rows yet.

    A bare MagicMock answers `target_rows_per_source_guid` with another mock, whose union
    and membership tests both quietly do nothing — so a test double has to state
    the empty set the real backend would return.
    """
    backend = MagicMock()
    backend.target_rows_per_source_guid.return_value = {}
    return backend


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

        _found, processed, _errors = process_directory_files(
            runner, input_dir, output, str(input_dir), params, set()
        )
        assert processed == 2
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

        _found, processed, _errors = process_directory_files(
            runner, input_dir, output, str(input_dir), params, set()
        )
        assert processed == 5

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

        _found, processed, _errors = process_directory_files(
            runner, input_dir, output, str(input_dir), params, set()
        )
        assert processed == 3


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

        _found, processed, _errors = process_merged_files(runner, params)
        assert processed == 2
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
            storage_backend=_backend_holding_nothing(),
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
    def test_a_retried_record_keeps_its_source_row(
        self, mock_process, mock_reader, mock_prep, mock_validate, mock_save
    ):
        """The source text is positionally aligned with the records, so both are
        kept by the same indices. Slicing it by the limit alone would save the
        first N rows while the records saved are the first N plus the retried."""
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )

        # Online mode returns one list under both names, as production does.
        rows = [{"source_guid": f"g{i}", "content": str(i)} for i in range(6)]
        mock_prep.return_value = (rows, rows)

        reader_instance = MagicMock()
        reader_instance.read.return_value = "raw"
        reader_instance.file_type = ".json"
        mock_reader.return_value = reader_instance
        mock_process.return_value = "/output/file.json"

        process_initial_stage(
            InitialStageContext(
                agent_config={"record_limit": 2, "run_mode": "online"},
                agent_name="test",
                file_path="/input/data.json",
                base_directory="/input",
                output_directory="/output",
                storage_backend=_backend_holding_nothing(),
                retried_records=frozenset({"g5"}),
            )
        )

        saved_src, saved_data = mock_save.call_args[0][0], mock_save.call_args[0][1]
        assert [r["source_guid"] for r in saved_data] == ["g0", "g1", "g5"]
        assert [r["source_guid"] for r in saved_src] == ["g0", "g1", "g5"]

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
            storage_backend=_backend_holding_nothing(),
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
            storage_backend=_backend_holding_nothing(),
        )

        process_initial_stage(ctx)

        save_args = mock_save.call_args
        saved_data = save_args[0][1]
        assert len(saved_data) == 5


# ── Status invalidation when limits change ────────────────────────────


class TestRecordLimitInitialStageUnderBatch:
    """Batch takes a different preparation path to online, and it is the path
    immediately before the batch/online fork that slices."""

    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._save_source_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._validate_staged_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._prepare_batch_data")
    @patch("agent_actions.input.loaders.file_reader.FileReader")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._process_batch_mode")
    def test_a_held_record_beyond_the_limit_is_kept(
        self, mock_process, mock_reader, mock_prep, mock_validate, mock_save
    ):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )

        rows = [{"source_guid": f"g{i}", "content": str(i)} for i in range(6)]
        mock_prep.return_value = (rows, [])
        reader_instance = MagicMock()
        reader_instance.read.return_value = "raw"
        reader_instance.file_type = ".json"
        mock_reader.return_value = reader_instance
        mock_process.return_value = "/output/file.json"
        backend = MagicMock()
        backend.target_rows_per_source_guid.return_value = {"g5": 1}

        process_initial_stage(
            InitialStageContext(
                agent_config={"record_limit": 2, "run_mode": "batch"},
                agent_name="test",
                file_path="/input/data.json",
                base_directory="/input",
                output_directory="/output",
                storage_backend=backend,
                retried_records=frozenset({"g5"}),
            )
        )

        saved_data = mock_save.call_args[0][1]
        assert [r["source_guid"] for r in saved_data] == ["g0", "g1", "g5"]


class TestDeduplicationUnderBatch:
    """The reduction sits above the batch/online fork, and batch is the path where
    src_text is empty — so the aligned half is exercised differently there."""

    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._save_source_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._validate_staged_data")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._prepare_batch_data")
    @patch("agent_actions.input.loaders.file_reader.FileReader")
    @patch("agent_actions.input.preprocessing.staging.initial_pipeline._process_batch_mode")
    def test_one_record_per_identity_reaches_the_save_and_the_batch(
        self, mock_process, mock_reader, mock_prep, mock_validate, mock_save
    ):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            InitialStageContext,
            process_initial_stage,
        )

        rows = [{"source_guid": g, "content": g} for g in ("g0", "g0", "g1")]
        mock_prep.return_value = (rows, [])
        reader_instance = MagicMock()
        reader_instance.read.return_value = "raw"
        reader_instance.file_type = ".json"
        mock_reader.return_value = reader_instance
        mock_process.return_value = "/output/file.json"

        process_initial_stage(
            InitialStageContext(
                agent_config={"run_mode": "batch"},
                agent_name="test",
                file_path="/input/data.json",
                base_directory="/input",
                output_directory="/output",
                storage_backend=_backend_holding_nothing(),
            )
        )

        saved = mock_save.call_args[0][1]
        assert [r["source_guid"] for r in saved] == ["g0", "g1"]
        batched = mock_process.call_args[0][0].data_chunk
        assert [r["source_guid"] for r in batched] == ["g0", "g1"], "the batch got the other list"


class TestLimitStatusInvalidation:
    @pytest.fixture
    def mock_deps(self):
        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = MagicMock(spec=ActionStateManager)
        deps.action_runner = MagicMock()
        deps.action_runner.retried_records = frozenset()
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


class TestTheCompletionStamp:
    """What a completed action stores, and which parts of it are compared."""

    @pytest.fixture
    def executor(self):
        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = MagicMock(spec=ActionStateManager)
        deps.action_runner = MagicMock()
        deps.action_runner.retried_records = frozenset()
        return ActionExecutor(deps)

    def test_it_stores_exactly_these_keys(self, executor):
        """Pinned as a set: a slot that silently reappears is how one limit
        source came to be recorded in a place nothing read."""
        stamp = executor._completion_metadata("act", {"record_limit": 2})

        assert set(stamp) == {
            "record_limit",
            "file_limit",
            "model_name",
            "model_vendor",
            "config_hash",
        }

    def test_a_changed_file_limit_invalidates(self, executor):
        """Its own term in the comparison, not carried by record_limit."""
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": 10,
            "file_limit": 2,
        }

        status = executor._maybe_invalidate_completed_status(
            "act", {"record_limit": 10, "file_limit": 5}, ActionStatus.COMPLETED
        )

        assert status == ActionStatus.PENDING

    def test_unchanged_limits_leave_the_action_completed(self, executor):
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": 10,
            "file_limit": 2,
        }

        status = executor._maybe_invalidate_completed_status(
            "act", {"record_limit": 10, "file_limit": 2}, ActionStatus.COMPLETED
        )

        assert status == ActionStatus.COMPLETED

    def test_a_retry_lets_a_changed_limit_stand(self, executor):
        """A retry asks for named records, not for a different amount of work.
        Invalidating here clears the action's dispositions and re-runs it
        truncated, losing records the retry never named."""
        executor.deps.action_runner.retried_records = frozenset({"some-record"})
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": 10,
            "file_limit": None,
        }

        status = executor._maybe_invalidate_completed_status(
            "act", {"record_limit": 2}, ActionStatus.COMPLETED
        )

        assert status == ActionStatus.COMPLETED

    def test_a_retry_leaves_the_stored_limit_where_it_found_it(self, executor):
        """The other half of suppressing the limit: recording the one a retry
        ran under would make the next ordinary run read a change, clear the
        action's dispositions and re-run it."""
        executor.deps.action_runner.retried_records = frozenset({"some-record"})
        executor.deps.state_manager.get_status_details.return_value = {"record_limit": None}

        stamp = executor._completion_metadata("act", {"record_limit": 2})

        assert stamp["record_limit"] is None

    def test_an_ordinary_run_stores_the_limit_in_force(self, executor):
        stamp = executor._completion_metadata("act", {"record_limit": 2})

        assert stamp["record_limit"] == 2

    def test_a_limit_that_could_not_truncate_still_invalidates(self, monkeypatch, executor):
        """Deliberate and coarse: the comparison never sees how many records
        exist, so it cannot tell a limit that bit from one that did not. The
        action re-runs and reproduces its full output; the cost is the work."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1000")
        executor.deps.state_manager.get_status_details.return_value = {
            "record_limit": None,
            "file_limit": None,
        }

        status = executor._maybe_invalidate_completed_status("act", {}, ActionStatus.COMPLETED)

        assert status == ActionStatus.PENDING


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
