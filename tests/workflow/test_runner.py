"""Tests for ActionRunner — covers init, folder lookup, directory setup,
file processing, storage backend, and orchestration methods."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.di.container import ProcessorFactory
from agent_actions.errors import FileSystemError
from agent_actions.workflow.runner import (
    ActionRunner,
    FileLocationParams,
    FileProcessParams,
    ProcessGenerateParams,
    SingleFileProcessParams,
)
from agent_actions.workflow.strategies import InitialStrategy, StandardStrategy

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def factory():
    return MagicMock(spec=ProcessorFactory)


@pytest.fixture()
def runner(factory):
    return ActionRunner(use_tools=True, processor_factory=factory)


@pytest.fixture()
def runner_with_backend(factory):
    backend = MagicMock()
    return ActionRunner(use_tools=True, processor_factory=factory, storage_backend=backend)


def _make_file(path: Path, content: str = "hello") -> Path:
    """Create a file (and parent dirs) with the given content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_strategy():
    """Return a mock AgentStrategy."""
    return MagicMock()


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_attributes_set(self, factory):
        runner = ActionRunner(use_tools=True, processor_factory=factory)
        assert runner.use_tools is True
        assert runner.processor_factory is factory
        assert runner.storage_backend is None
        assert runner.action_configs is None
        assert runner.execution_order == []
        assert runner.action_indices == {}
        assert runner.workflow_name is None
        assert runner.manifest_manager is None
        assert runner.data_source_config is None
        assert runner.project_root is None

    def test_creates_three_strategies(self, factory):
        runner = ActionRunner(use_tools=True, processor_factory=factory)
        assert set(runner.strategies.keys()) == {"initial", "intermediate", "terminal"}
        assert isinstance(runner.strategies["initial"], InitialStrategy)
        assert isinstance(runner.strategies["intermediate"], StandardStrategy)
        assert isinstance(runner.strategies["terminal"], StandardStrategy)

    def test_storage_backend_set(self, factory):
        backend = MagicMock()
        runner = ActionRunner(use_tools=True, processor_factory=factory, storage_backend=backend)
        assert runner.storage_backend is backend


# ---------------------------------------------------------------------------
# get_action_folder
# ---------------------------------------------------------------------------


class TestGetAgentFolder:
    @patch("agent_actions.workflow.runner.FileHandler.find_specific_folder")
    def test_returns_folder_when_found(self, mock_find, runner):
        mock_find.return_value = "/some/path/agent_io"
        result = runner.get_action_folder("my_agent", project_root=Path("/root"))
        assert result == "/some/path/agent_io"
        mock_find.assert_called_once_with("/root", "my_agent", "agent_io")

    @patch("agent_actions.workflow.runner.FileHandler.find_specific_folder")
    def test_raises_when_not_found(self, mock_find, runner):
        mock_find.return_value = None
        with pytest.raises(FileSystemError, match="Action folder not found"):
            runner.get_action_folder("missing_agent", project_root=Path("/root"))

    @patch("agent_actions.workflow.runner.FileHandler.find_specific_folder")
    def test_uses_workflow_name_over_agent_name(self, mock_find, runner):
        runner.workflow_name = "my_workflow"
        mock_find.return_value = "/path"
        runner.get_action_folder("my_agent", project_root=Path("/root"))
        mock_find.assert_called_once_with("/root", "my_workflow", "agent_io")

    @patch("agent_actions.workflow.runner.FileHandler.find_specific_folder")
    def test_uses_project_root_attribute(self, mock_find, runner):
        runner.project_root = Path("/project")
        mock_find.return_value = "/path"
        runner.get_action_folder("agent_a")
        mock_find.assert_called_once_with("/project", "agent_a", "agent_io")


# ---------------------------------------------------------------------------
# _resolve_upstream_from_manifest
# ---------------------------------------------------------------------------


class TestResolveUpstreamFromManifest:
    @patch("agent_actions.workflow.runner.ArtifactLinker.read_manifest")
    def test_no_manifest_returns_none(self, mock_read, runner):
        mock_read.return_value = None
        result = runner._resolve_upstream_from_manifest(Path("/agent/agent_io"))
        assert result is None

    @patch("agent_actions.workflow.runner.ArtifactLinker.read_manifest")
    def test_manifest_with_existing_path(self, mock_read, runner, tmp_path):
        upstream = tmp_path / "upstream"
        upstream.mkdir()
        mock_read.return_value = {"upstream_path": str(upstream)}
        result = runner._resolve_upstream_from_manifest(tmp_path / "agent_io")
        assert result == [upstream]

    @patch("agent_actions.workflow.runner.ArtifactLinker.read_manifest")
    def test_manifest_upstream_missing(self, mock_read, runner, tmp_path):
        mock_read.return_value = {"upstream_path": str(tmp_path / "nonexistent")}
        result = runner._resolve_upstream_from_manifest(tmp_path / "agent_io")
        assert result is None

    @patch("agent_actions.workflow.runner.ArtifactLinker.read_manifest")
    def test_no_double_agent_io_nesting(self, mock_read, runner, tmp_path):
        """When 'agent_io' is already in the folder path, don't nest it again."""
        agent_io_path = tmp_path / "agent_io"
        agent_io_path.mkdir()
        mock_read.return_value = None
        runner._resolve_upstream_from_manifest(agent_io_path)
        # Should call read_manifest with the same path, not agent_io/agent_io
        mock_read.assert_called_once_with(agent_io_path)


# ---------------------------------------------------------------------------
# _resolve_start_node_directories
# ---------------------------------------------------------------------------


class TestResolveStartNodeDirectories:
    @patch("agent_actions.workflow.runner.ArtifactLinker.read_manifest")
    def test_manifest_resolves_first(self, mock_read, runner, tmp_path):
        upstream = tmp_path / "upstream"
        upstream.mkdir()
        mock_read.return_value = {"upstream_path": str(upstream)}
        result = runner._resolve_start_node_directories(tmp_path / "agent_io", "agent")
        assert result == [upstream]

    @patch("agent_actions.workflow.runner.resolve_start_node_data_source")
    @patch("agent_actions.workflow.runner.ArtifactLinker.read_manifest")
    def test_falls_back_to_data_source(self, mock_read, mock_resolve, runner, tmp_path):
        mock_read.return_value = None
        staging = tmp_path / "staging"
        staging.mkdir()
        mock_result = MagicMock()
        mock_result.directories = [staging]
        mock_resolve.return_value = mock_result
        result = runner._resolve_start_node_directories(tmp_path, "agent")
        assert result == [staging]
        mock_resolve.assert_called_once()


# ---------------------------------------------------------------------------
# _resolve_single_dependency
# ---------------------------------------------------------------------------


class TestResolveSingleDependency:
    def test_storage_backend_virtual_path(self, runner_with_backend, tmp_path):
        """Storage backend has files → returns virtual path."""
        backend = runner_with_backend.storage_backend
        backend.list_target_files.return_value = ["data.json"]
        target_dir = tmp_path / "target"
        result = runner_with_backend._resolve_single_dependency(target_dir, "dep1")
        assert result == target_dir / "dep1"

    def test_storage_backend_no_files_falls_through(self, runner_with_backend, tmp_path):
        """Storage backend has no files → falls through to manifest/filesystem."""
        backend = runner_with_backend.storage_backend
        backend.list_target_files.return_value = []
        target_dir = tmp_path / "target"
        # No manifest_manager, no filesystem path → returns None
        result = runner_with_backend._resolve_single_dependency(target_dir, "dep1")
        assert result is None

    def test_storage_backend_exception_falls_through(self, runner_with_backend, tmp_path):
        """Storage backend raises → falls through gracefully."""
        backend = runner_with_backend.storage_backend
        backend.list_target_files.side_effect = Exception("db error")
        target_dir = tmp_path / "target"
        result = runner_with_backend._resolve_single_dependency(target_dir, "dep1")
        assert result is None

    def test_manifest_manager_resolves(self, runner, tmp_path):
        """ManifestManager resolves dependency path."""
        target_dir = tmp_path / "target"
        dep_path = tmp_path / "output" / "dep1"
        dep_path.mkdir(parents=True)
        runner.manifest_manager = MagicMock()
        runner.manifest_manager.get_output_directory.return_value = dep_path
        result = runner._resolve_single_dependency(target_dir, "dep1")
        assert result == dep_path

    def test_manifest_manager_key_error_falls_through(self, runner, tmp_path):
        """ManifestManager raises KeyError → falls through to filesystem."""
        target_dir = tmp_path / "target"
        runner.manifest_manager = MagicMock()
        runner.manifest_manager.get_output_directory.side_effect = KeyError("dep1")
        result = runner._resolve_single_dependency(target_dir, "dep1")
        assert result is None

    def test_filesystem_fallback(self, runner, tmp_path):
        """Direct filesystem path exists → returns it."""
        target_dir = tmp_path / "target"
        dep_path = target_dir / "dep1"
        dep_path.mkdir(parents=True)
        result = runner._resolve_single_dependency(target_dir, "dep1")
        assert result == dep_path


# ---------------------------------------------------------------------------
# setup_directories
# ---------------------------------------------------------------------------


class TestSetupDirectories:
    @patch.object(ActionRunner, "_resolve_start_node_directories")
    def test_no_deps_no_previous(self, mock_resolve, runner, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        mock_resolve.return_value = [staging]
        config = {"agent_type": "analyzer"}
        dirs, output = runner.setup_directories(str(tmp_path), config, None, 0)
        assert dirs == [str(staging)]
        assert "target/analyzer" in output
        mock_resolve.assert_called_once()

    @patch.object(ActionRunner, "_resolve_dependency_directories")
    def test_has_deps_and_indices(self, mock_dep, runner, tmp_path):
        dep_dir = tmp_path / "target" / "dep1"
        dep_dir.mkdir(parents=True)
        mock_dep.return_value = [dep_dir]
        runner.action_indices = {"analyzer": 0, "dep1": 1}
        config = {"agent_type": "analyzer", "dependencies": ["dep1"]}
        dirs, output = runner.setup_directories(str(tmp_path), config, None, 0)
        assert dirs == [str(dep_dir)]
        mock_dep.assert_called_once()

    def test_has_previous_agent_type(self, runner, tmp_path):
        config = {"agent_type": "analyzer"}
        dirs, output = runner.setup_directories(str(tmp_path), config, "extractor", 0)
        assert dirs == [str(tmp_path / "target" / "extractor")]

    def test_fallback_to_staging(self, runner, tmp_path):
        runner.action_indices = {}
        config = {"agent_type": "analyzer", "dependencies": ["dep1"]}
        dirs, output = runner.setup_directories(str(tmp_path), config, None, 0)
        assert dirs == [str(tmp_path / "staging")]

    def test_creates_output_dir_no_backend(self, runner, tmp_path):
        config = {"agent_type": "analyzer"}
        _dirs, output = runner.setup_directories(str(tmp_path), config, "prev", 0)
        assert Path(output).exists()

    def test_skips_mkdir_with_backend(self, runner_with_backend, tmp_path):
        config = {"agent_type": "analyzer"}
        _dirs, output = runner_with_backend.setup_directories(str(tmp_path), config, "prev", 0)
        assert not Path(output).exists()


# ---------------------------------------------------------------------------
# _should_skip_item
# ---------------------------------------------------------------------------


class TestShouldSkipItem:
    def test_batch_in_path(self, runner, tmp_path):
        batch_dir = tmp_path / "batch"
        batch_dir.mkdir()
        item = batch_dir / "file.json"
        item.touch()
        assert runner._should_skip_item(item, tmp_path, set()) is True

    def test_directory_skipped(self, runner, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        assert runner._should_skip_item(sub, tmp_path, set()) is True

    def test_dotfile_skipped(self, runner, tmp_path):
        dotfile = tmp_path / ".hidden"
        dotfile.touch()
        assert runner._should_skip_item(dotfile, tmp_path, set()) is True

    def test_already_processed(self, runner, tmp_path):
        f = _make_file(tmp_path / "data.json")
        processed = {Path("data.json")}
        assert runner._should_skip_item(f, tmp_path, processed) is True

    def test_file_type_filter_mismatch(self, runner, tmp_path):
        f = _make_file(tmp_path / "data.csv")
        assert runner._should_skip_item(f, tmp_path, set(), file_type_filter={"json"}) is True

    def test_valid_file_not_skipped(self, runner, tmp_path):
        f = _make_file(tmp_path / "data.json")
        assert runner._should_skip_item(f, tmp_path, set()) is False

    def test_valid_file_with_matching_filter(self, runner, tmp_path):
        f = _make_file(tmp_path / "data.json")
        assert runner._should_skip_item(f, tmp_path, set(), file_type_filter={"json"}) is False


# ---------------------------------------------------------------------------
# _collect_files_from_upstream
# ---------------------------------------------------------------------------


class TestCollectFilesFromUpstream:
    def test_single_dir_with_files(self, runner, tmp_path):
        _make_file(tmp_path / "a.json")
        _make_file(tmp_path / "sub" / "b.json")
        result = runner._collect_files_from_upstream([str(tmp_path)])
        assert len(result) == 2
        assert Path("a.json") in result
        assert Path("sub/b.json") in result

    def test_nonexistent_dir_skipped(self, runner, tmp_path):
        result = runner._collect_files_from_upstream([str(tmp_path / "nope")])
        assert result == {}

    def test_skips_batch_and_dotfiles(self, runner, tmp_path):
        _make_file(tmp_path / "batch" / "x.json")
        _make_file(tmp_path / ".hidden")
        _make_file(tmp_path / "good.json")
        result = runner._collect_files_from_upstream([str(tmp_path)])
        assert len(result) == 1
        assert Path("good.json") in result

    def test_groups_same_relative_from_multiple_dirs(self, runner, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        _make_file(dir1 / "shared.json", "one")
        _make_file(dir2 / "shared.json", "two")
        result = runner._collect_files_from_upstream([str(dir1), str(dir2)])
        assert len(result) == 1
        assert len(result[Path("shared.json")]) == 2


# ---------------------------------------------------------------------------
# _process_single_file
# ---------------------------------------------------------------------------


class TestProcessSingleFile:
    def test_calls_strategy_execute(self, runner, tmp_path):
        strategy = _make_strategy()
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        f = _make_file(input_dir / "data.json")

        params = SingleFileProcessParams(
            locations=FileLocationParams(
                item=f, input_path=input_dir, output_path=output_dir, input_directory=str(input_dir)
            ),
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            idx=0,
        )
        runner._process_single_file(params)
        strategy.execute.assert_called_once()
        call_args = strategy.execute.call_args[0][0]
        assert call_args.action_name == "test_agent"
        assert call_args.file_path == str(f)

    def test_creates_parent_dirs_no_backend(self, runner, tmp_path):
        strategy = _make_strategy()
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output" / "deep"
        f = _make_file(input_dir / "sub" / "data.json")

        params = SingleFileProcessParams(
            locations=FileLocationParams(
                item=f, input_path=input_dir, output_path=output_dir, input_directory=str(input_dir)
            ),
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            idx=0,
        )
        runner._process_single_file(params)
        assert (output_dir / "sub").exists()

    def test_skips_mkdir_with_backend(self, runner_with_backend, tmp_path):
        strategy = _make_strategy()
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output" / "deep"
        f = _make_file(input_dir / "data.json")

        params = SingleFileProcessParams(
            locations=FileLocationParams(
                item=f, input_path=input_dir, output_path=output_dir, input_directory=str(input_dir)
            ),
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            idx=0,
        )
        runner_with_backend._process_single_file(params)
        assert not output_dir.exists()


# ---------------------------------------------------------------------------
# _process_directory_files
# ---------------------------------------------------------------------------


class TestProcessDirectoryFiles:
    def test_processes_valid_files(self, runner, tmp_path):
        strategy = _make_strategy()
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)
        _make_file(input_dir / "a.json")
        _make_file(input_dir / "b.json")

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(input_dir)],
            output_directory=str(output_dir),
            idx=0,
        )
        count = runner._process_directory_files(
            input_dir, output_dir, str(input_dir), params, set()
        )
        assert count == 2
        assert strategy.execute.call_count == 2

    def test_skips_per_should_skip(self, runner, tmp_path):
        strategy = _make_strategy()
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)
        _make_file(input_dir / ".hidden")
        _make_file(input_dir / "batch" / "skip.json")
        _make_file(input_dir / "good.json")

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(input_dir)],
            output_directory=str(output_dir),
            idx=0,
        )
        count = runner._process_directory_files(
            input_dir, output_dir, str(input_dir), params, set()
        )
        assert count == 1


# ---------------------------------------------------------------------------
# _warn_no_files_found
# ---------------------------------------------------------------------------


class TestWarnNoFilesFound:
    @patch("agent_actions.workflow.runner_file_processing.logger")
    def test_logs_when_no_content(self, mock_logger, runner, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=_make_strategy(),
            upstream_data_dirs=[str(empty_dir)],
            output_directory=str(tmp_path / "out"),
            idx=0,
        )
        runner._warn_no_files_found(params)
        mock_logger.warning.assert_called_once()
        assert "No files found" in mock_logger.warning.call_args[0][0]

    @patch("agent_actions.workflow.runner_file_processing.logger")
    def test_no_warn_when_content_exists(self, mock_logger, runner, tmp_path):
        d = tmp_path / "data"
        _make_file(d / "f.json")
        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=_make_strategy(),
            upstream_data_dirs=[str(d)],
            output_directory=str(tmp_path / "out"),
            idx=0,
        )
        runner._warn_no_files_found(params)
        mock_logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# _process_merged_files
# ---------------------------------------------------------------------------


class TestProcessMergedFiles:
    def test_single_file_passthrough(self, runner, tmp_path):
        strategy = _make_strategy()
        upstream = tmp_path / "upstream"
        _make_file(upstream / "data.json", json.dumps([{"id": 1}]))
        output = tmp_path / "output"

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(upstream)],
            output_directory=str(output),
            idx=0,
        )
        count = runner._process_merged_files(params)
        assert count == 1
        strategy.execute.assert_called_once()

    @patch("agent_actions.workflow.runner_file_processing.merge_json_files")
    def test_multiple_files_merges(self, mock_merge, runner, tmp_path):
        strategy = _make_strategy()
        dir1 = tmp_path / "d1"
        dir2 = tmp_path / "d2"
        _make_file(dir1 / "data.json", json.dumps([{"id": 1}]))
        _make_file(dir2 / "data.json", json.dumps([{"id": 2}]))
        output = tmp_path / "output"

        mock_merge.return_value = [{"id": 1}, {"id": 2}]
        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(dir1), str(dir2)],
            output_directory=str(output),
            idx=0,
        )
        count = runner._process_merged_files(params)
        assert count == 1
        mock_merge.assert_called_once()
        strategy.execute.assert_called_once()

    @patch("agent_actions.workflow.runner_file_processing.merge_json_files")
    def test_restores_original_content_after_merge(self, mock_merge, runner, tmp_path):
        strategy = _make_strategy()
        dir1 = tmp_path / "d1"
        dir2 = tmp_path / "d2"
        original_content = json.dumps([{"id": 1}])
        _make_file(dir1 / "data.json", original_content)
        _make_file(dir2 / "data.json", json.dumps([{"id": 2}]))
        output = tmp_path / "output"

        mock_merge.return_value = [{"id": 1}, {"id": 2}]
        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(dir1), str(dir2)],
            output_directory=str(output),
            idx=0,
        )
        runner._process_merged_files(params)
        # Original content should be restored
        assert (dir1 / "data.json").read_text(encoding="utf-8") == original_content


# ---------------------------------------------------------------------------
# _process_from_storage_backend
# ---------------------------------------------------------------------------


class TestProcessFromStorageBackend:
    def test_no_backend_returns_zero(self, runner):
        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=_make_strategy(),
            upstream_data_dirs=["/some/target/dep"],
            output_directory="/out",
            idx=0,
        )
        assert runner._process_from_storage_backend(params) == (0, 0)

    def test_skips_staging_directories(self, runner_with_backend, tmp_path):
        backend = runner_with_backend.storage_backend
        backend.list_target_files.return_value = []
        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=_make_strategy(),
            upstream_data_dirs=[str(tmp_path / "staging" / "dep")],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        result = runner_with_backend._process_from_storage_backend(params)
        assert result == (0, 0)
        backend.list_target_files.assert_not_called()

    def test_single_source_processes(self, runner_with_backend, tmp_path):
        backend = runner_with_backend.storage_backend
        backend.list_target_files.return_value = ["data.json"]
        backend.read_target.return_value = [{"id": 1}]
        strategy = _make_strategy()

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(tmp_path / "target" / "dep1")],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        found, processed = runner_with_backend._process_from_storage_backend(params)
        assert found == 1
        assert processed == 1
        strategy.execute.assert_called_once()

    @patch("agent_actions.workflow.runner_file_processing.merge_records_by_key")
    def test_multiple_sources_merges(self, mock_merge, runner_with_backend, tmp_path):
        backend = runner_with_backend.storage_backend
        backend.list_target_files.side_effect = [["data.json"], ["data.json"]]
        backend.read_target.side_effect = [[{"id": 1}], [{"id": 2}]]
        mock_merge.return_value = [{"id": 1}, {"id": 2}]
        strategy = _make_strategy()

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[
                str(tmp_path / "target" / "dep1"),
                str(tmp_path / "target" / "dep2"),
            ],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        found, processed = runner_with_backend._process_from_storage_backend(params)
        assert found == 1
        assert processed == 1
        mock_merge.assert_called_once()

    def test_processing_error_returns_partial(self, runner_with_backend, tmp_path):
        backend = runner_with_backend.storage_backend
        backend.list_target_files.return_value = ["a.json", "b.json"]
        backend.read_target.side_effect = [[{"id": 1}], [{"id": 2}]]
        strategy = _make_strategy()
        strategy.execute.side_effect = [None, Exception("boom")]

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(tmp_path / "target" / "dep")],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        found, processed = runner_with_backend._process_from_storage_backend(params)
        assert found == 2
        assert processed == 1

    def test_read_target_exception_skips_entry(self, runner_with_backend, tmp_path):
        """read_target() failure → entry skipped, partial results returned."""
        backend = runner_with_backend.storage_backend
        backend.list_target_files.return_value = ["good.json", "bad.json"]
        backend.read_target.side_effect = [[{"id": 1}], Exception("corrupt data")]
        strategy = _make_strategy()

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(tmp_path / "target" / "dep")],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        found, processed = runner_with_backend._process_from_storage_backend(params)
        # good.json was read and processed; bad.json failed to read → only 1 file in data_by_path
        assert found == 1
        assert processed == 1

    def test_list_target_files_exception_continues(self, runner_with_backend, tmp_path):
        backend = runner_with_backend.storage_backend
        backend.list_target_files.side_effect = Exception("connection lost")

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=_make_strategy(),
            upstream_data_dirs=[str(tmp_path / "target" / "dep")],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        found, processed = runner_with_backend._process_from_storage_backend(params)
        assert found == 0
        assert processed == 0


# ---------------------------------------------------------------------------
# _is_target_directory
# ---------------------------------------------------------------------------


class TestIsTargetDirectory:
    def test_target_path(self, runner):
        assert runner._is_target_directory("/project/agent_io/target/dep") is True

    def test_staging_path(self, runner):
        assert runner._is_target_directory("/project/agent_io/staging/data") is False

    def test_both_target_and_staging(self, runner):
        assert runner._is_target_directory("/project/target/staging/dep") is False


# ---------------------------------------------------------------------------
# process_files
# ---------------------------------------------------------------------------


class TestProcessFiles:
    def test_storage_backend_all_targets_processed(self, runner_with_backend, tmp_path):
        """Storage backend processes successfully → returns early."""
        backend = runner_with_backend.storage_backend
        backend.list_target_files.return_value = ["data.json"]
        backend.read_target.return_value = [{"id": 1}]
        strategy = _make_strategy()

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(tmp_path / "target" / "dep")],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        runner_with_backend.process_files(params)
        strategy.execute.assert_called_once()

    def test_storage_backend_found_but_not_processed_raises(self, runner_with_backend, tmp_path):
        """Data found in DB but processing failed → DependencyError."""
        from agent_actions.errors import DependencyError

        backend = runner_with_backend.storage_backend
        backend.list_target_files.return_value = ["data.json"]
        backend.read_target.return_value = [{"id": 1}]
        strategy = _make_strategy()
        strategy.execute.side_effect = Exception("fail")

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(tmp_path / "target" / "dep")],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        with pytest.raises(DependencyError, match="Found .* files in storage"):
            runner_with_backend.process_files(params)

    def test_storage_backend_no_data_falls_through(self, runner_with_backend, tmp_path):
        """No data in backend → falls through to filesystem."""
        backend = runner_with_backend.storage_backend
        backend.list_target_files.return_value = []
        strategy = _make_strategy()

        input_dir = tmp_path / "target" / "dep"
        _make_file(input_dir / "data.json")
        output_dir = tmp_path / "output"

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(input_dir)],
            output_directory=str(output_dir),
            idx=0,
        )
        runner_with_backend.process_files(params)
        strategy.execute.assert_called_once()

    @patch("agent_actions.workflow.runner_file_processing.merge_json_files")
    def test_multi_upstream_same_name_merges(self, mock_merge, runner, tmp_path):
        """Multiple upstream dirs with same dep name → _process_merged_files."""
        strategy = _make_strategy()
        d1 = tmp_path / "target" / "dep"
        d2 = tmp_path / "target2" / "dep"
        _make_file(d1 / "data.json", json.dumps([{"id": 1}]))
        _make_file(d2 / "data.json", json.dumps([{"id": 2}]))
        mock_merge.return_value = [{"id": 1}, {"id": 2}]

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(d1), str(d2)],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        runner.process_files(params)
        mock_merge.assert_called_once()
        strategy.execute.assert_called_once()

    def test_multi_upstream_different_names_merges(self, runner, tmp_path):
        """Multiple upstream dirs with different names → aggregation merge."""
        strategy = _make_strategy()
        d1 = tmp_path / "target" / "dep1"
        d2 = tmp_path / "target" / "dep2"
        _make_file(d1 / "unique1.json", json.dumps([{"id": 1}]))
        _make_file(d2 / "unique2.json", json.dumps([{"id": 2}]))

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(d1), str(d2)],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        runner.process_files(params)
        assert strategy.execute.call_count == 2

    def test_single_upstream_dir(self, runner, tmp_path):
        """Single upstream dir → _process_directory_files."""
        strategy = _make_strategy()
        input_dir = tmp_path / "input"
        _make_file(input_dir / "a.json")
        _make_file(input_dir / "b.json")

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(input_dir)],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        runner.process_files(params)
        assert strategy.execute.call_count == 2

    @patch("agent_actions.workflow.runner_file_processing.logger")
    def test_no_files_warns(self, mock_logger, runner, tmp_path):
        """No files found → calls _warn_no_files_found."""
        strategy = _make_strategy()
        empty = tmp_path / "empty"
        empty.mkdir()

        params = FileProcessParams(
            action_config={"agent_type": "test"},
            action_name="test_agent",
            strategy=strategy,
            upstream_data_dirs=[str(empty)],
            output_directory=str(tmp_path / "output"),
            idx=0,
        )
        runner.process_files(params)
        mock_logger.warning.assert_called()
        assert any("No files found" in str(c) for c in mock_logger.warning.call_args_list)


# ---------------------------------------------------------------------------
# run_action
# ---------------------------------------------------------------------------


class TestRunAgent:
    @patch.object(ActionRunner, "process_and_generate_for_action")
    def test_no_deps_uses_initial_strategy(self, mock_pga, runner):
        mock_pga.return_value = "/output"
        config = {"agent_type": "analyzer"}
        runner.run_action(config, "analyzer", None, 0)
        call_params = mock_pga.call_args[0][0]
        assert call_params.strategy is runner.strategies["initial"]

    @patch.object(ActionRunner, "process_and_generate_for_action")
    def test_has_deps_uses_intermediate_strategy(self, mock_pga, runner):
        mock_pga.return_value = "/output"
        config = {"agent_type": "analyzer", "dependencies": ["dep1"]}
        runner.run_action(config, "analyzer", None, 0)
        call_params = mock_pga.call_args[0][0]
        assert call_params.strategy is runner.strategies["intermediate"]

    @patch.object(ActionRunner, "process_and_generate_for_action")
    def test_returns_output_folder(self, mock_pga, runner):
        mock_pga.return_value = "/output/target/analyzer"
        config = {"agent_type": "analyzer"}
        result = runner.run_action(config, "analyzer", None, 0)
        assert result == "/output/target/analyzer"


# ---------------------------------------------------------------------------
# process_and_generate_for_action
# ---------------------------------------------------------------------------


class TestProcessAndGenerateForAgent:
    @patch.object(ActionRunner, "process_files")
    @patch.object(ActionRunner, "setup_directories")
    @patch.object(ActionRunner, "get_action_folder")
    def test_orchestrates_correctly(self, mock_folder, mock_setup, mock_process, runner):
        mock_folder.return_value = "/agent_io"
        mock_setup.return_value = (["/input"], "/output")
        strategy = _make_strategy()

        params = ProcessGenerateParams(
            action_config={"agent_type": "analyzer", "dependencies": ["dep"]},
            action_name="analyzer",
            strategy=strategy,
            previous_action_type="extractor",
            idx=0,
        )
        result = runner.process_and_generate_for_action(params)
        assert result == "/output"
        mock_folder.assert_called_once_with("analyzer")
        mock_setup.assert_called_once()
        mock_process.assert_called_once()

    @patch("agent_actions.workflow.runner.resolve_start_node_data_source")
    @patch.object(ActionRunner, "process_files")
    @patch.object(ActionRunner, "setup_directories")
    @patch.object(ActionRunner, "get_action_folder")
    @patch.object(ActionRunner, "_resolve_upstream_from_manifest")
    def test_resolves_file_type_filter_for_start_node(
        self, mock_manifest, mock_folder, mock_setup, mock_process, mock_resolve, runner
    ):
        mock_folder.return_value = "/agent_io"
        mock_setup.return_value = (["/input"], "/output")
        mock_manifest.return_value = None
        mock_result = MagicMock()
        mock_result.file_type_filter = {"pdf", "docx"}
        mock_resolve.return_value = mock_result

        params = ProcessGenerateParams(
            action_config={"agent_type": "analyzer"},
            action_name="analyzer",
            strategy=_make_strategy(),
            previous_action_type=None,
            idx=0,
        )
        runner.process_and_generate_for_action(params)
        # process_files should receive the file_type_filter
        file_params = mock_process.call_args[0][0]
        assert file_params.file_type_filter == {"pdf", "docx"}
