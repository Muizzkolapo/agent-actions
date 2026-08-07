"""Tests for the retry manifest checkpoint (crash-safe disposition clearing)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.retry import (
    RetryCommand,
    _delete_manifest,
    _manifest_path,
    _read_manifest,
    _write_manifest,
)
from tests.unit.cli.conftest import make_mock_backend


class TestManifestHelpers:
    """Unit tests for _manifest_path, _write_manifest, _read_manifest, _delete_manifest."""

    def test_manifest_path(self, tmp_path: Path):
        result = _manifest_path(tmp_path / "store" / "my_wf")
        assert result == tmp_path / "store" / "my_wf" / "_retry_manifest.json"

    def test_write_manifest_creates_file(self, tmp_path: Path):
        path = tmp_path / "store" / "my_wf" / "_retry_manifest.json"
        _write_manifest(
            path,
            from_action="classify",
            record_ids=["r1", "r2"],
            downstream_actions=["classify", "enrich"],
            dispositions=[
                {
                    "action_name": "classify",
                    "record_id": "r1",
                    "disposition": "failed",
                    "reason": "API error",
                },
            ],
        )
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["from_action"] == "classify"
        assert data["record_ids"] == ["r1", "r2"]
        assert data["downstream_actions"] == ["classify", "enrich"]
        assert len(data["dispositions"]) == 1
        assert "created_at" in data

    def test_write_manifest_sorts_record_ids(self, tmp_path: Path):
        path = tmp_path / "_retry_manifest.json"
        _write_manifest(path, "act", ["z", "a", "m"], ["act"], [])
        data = json.loads(path.read_text())
        assert data["record_ids"] == ["a", "m", "z"]

    def test_write_manifest_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "deep" / "nested" / "_retry_manifest.json"
        _write_manifest(path, "act", [], [], [])
        assert path.exists()

    def test_read_manifest_returns_none_when_absent(self, tmp_path: Path):
        result = _read_manifest(tmp_path / "nonexistent.json")
        assert result is None

    def test_read_manifest_returns_dict(self, tmp_path: Path):
        path = tmp_path / "_retry_manifest.json"
        _write_manifest(path, "act", ["r1"], ["act"], [{"x": 1}])
        result = _read_manifest(path)
        assert result is not None
        assert result["from_action"] == "act"

    def test_read_manifest_returns_none_for_corrupt_json(self, tmp_path: Path):
        path = tmp_path / "_retry_manifest.json"
        path.write_text("not valid json {{{", encoding="utf-8")
        result = _read_manifest(path)
        assert result is None

    def test_delete_manifest_removes_file(self, tmp_path: Path):
        path = tmp_path / "_retry_manifest.json"
        path.write_text("{}", encoding="utf-8")
        _delete_manifest(path)
        assert not path.exists()

    def test_delete_manifest_noop_when_absent(self, tmp_path: Path):
        path = tmp_path / "nonexistent.json"
        _delete_manifest(path)  # should not raise


class TestManifestWriteBeforeClear:
    """Manifest must be written BEFORE dispositions are cleared."""

    def test_manifest_written_before_clear(self, tmp_path: Path):
        """The manifest file must exist before clear_disposition is called."""
        store_dir = tmp_path / "agent_io" / "store" / "test_wf"
        store_dir.mkdir(parents=True)
        manifest_file = _manifest_path(store_dir)

        call_order: list[str] = []

        def track_write_manifest(*_args, **_kwargs):
            call_order.append("write_manifest")
            # Actually write the file so the assertion can check it
            _write_manifest(
                manifest_file,
                "classify",
                ["r1"],
                ["classify"],
                [
                    {
                        "action_name": "classify",
                        "record_id": "r1",
                        "disposition": "failed",
                        "reason": "err",
                    }
                ],
            )

        def track_clear(*_args, **_kwargs):
            call_order.append("clear_disposition")
            return 1

        backend = make_mock_backend(
            {
                "classify": [
                    {
                        "action_name": "classify",
                        "record_id": "r1",
                        "disposition": "failed",
                        "reason": "API error",
                    },
                ],
            }
        )
        backend.clear_disposition = MagicMock(side_effect=track_clear)

        with (
            patch("agent_actions.cli.retry._write_manifest", side_effect=track_write_manifest),
            patch("agent_actions.cli.retry.get_storage_backend", return_value=backend),
            patch("agent_actions.cli.retry.ProjectPathsFactory") as mock_paths_factory,
            patch("agent_actions.cli.retry.load_workflow") as mock_load_wf,
        ):
            mock_paths = MagicMock()
            mock_paths.io_dir = tmp_path / "agent_io"
            mock_paths_factory.create_project_paths.return_value = mock_paths

            mock_wf = MagicMock()
            mock_wf.execution_order = ["classify"]
            mock_load_wf.return_value = mock_wf

            args = RetryCommandArgs(agent="test_wf")
            cmd = RetryCommand(args)
            cmd.console = MagicMock()
            cmd.execute()

        assert call_order.index("write_manifest") < call_order.index("clear_disposition")


class TestManifestDeletedAfterSuccess:
    """Manifest is deleted after workflow.run() completes successfully."""

    def test_manifest_deleted_after_successful_run(self, tmp_path: Path):
        store_dir = tmp_path / "agent_io" / "store" / "test_wf"
        store_dir.mkdir(parents=True)
        manifest_file = _manifest_path(store_dir)

        backend = make_mock_backend(
            {
                "classify": [
                    {
                        "action_name": "classify",
                        "record_id": "r1",
                        "disposition": "failed",
                        "reason": "err",
                    },
                ],
            }
        )

        with (
            patch("agent_actions.cli.retry.get_storage_backend", return_value=backend),
            patch("agent_actions.cli.retry.ProjectPathsFactory") as mock_paths_factory,
            patch("agent_actions.cli.retry.load_workflow") as mock_load_wf,
        ):
            mock_paths = MagicMock()
            mock_paths.io_dir = tmp_path / "agent_io"
            mock_paths_factory.create_project_paths.return_value = mock_paths

            mock_wf = MagicMock()
            mock_wf.execution_order = ["classify"]
            mock_load_wf.return_value = mock_wf

            args = RetryCommandArgs(agent="test_wf")
            cmd = RetryCommand(args)
            cmd.console = MagicMock()
            cmd.execute()

        # Manifest should NOT exist after successful completion
        assert not manifest_file.exists()


class TestManifestSurvivesInterruption:
    """If workflow.run() raises, the manifest remains for recovery."""

    def test_manifest_survives_keyboard_interrupt(self, tmp_path: Path):
        store_dir = tmp_path / "agent_io" / "store" / "test_wf"
        store_dir.mkdir(parents=True)
        manifest_file = _manifest_path(store_dir)

        backend = make_mock_backend(
            {
                "classify": [
                    {
                        "action_name": "classify",
                        "record_id": "r1",
                        "disposition": "failed",
                        "reason": "API error",
                    },
                ],
            }
        )

        with (
            patch("agent_actions.cli.retry.get_storage_backend", return_value=backend),
            patch("agent_actions.cli.retry.ProjectPathsFactory") as mock_paths_factory,
            patch("agent_actions.cli.retry.load_workflow") as mock_load_wf,
        ):
            mock_paths = MagicMock()
            mock_paths.io_dir = tmp_path / "agent_io"
            mock_paths_factory.create_project_paths.return_value = mock_paths

            mock_wf = MagicMock()
            mock_wf.execution_order = ["classify"]
            mock_wf.run.side_effect = KeyboardInterrupt
            mock_load_wf.return_value = mock_wf

            args = RetryCommandArgs(agent="test_wf")
            cmd = RetryCommand(args)
            cmd.console = MagicMock()

            with pytest.raises(KeyboardInterrupt):
                cmd.execute()

        # Manifest must survive — it's the recovery checkpoint
        assert manifest_file.exists()
        data = json.loads(manifest_file.read_text())
        assert data["from_action"] == "classify"
        assert "r1" in data["record_ids"]
        assert len(data["dispositions"]) == 1

    def test_manifest_survives_runtime_error(self, tmp_path: Path):
        store_dir = tmp_path / "agent_io" / "store" / "test_wf"
        store_dir.mkdir(parents=True)
        manifest_file = _manifest_path(store_dir)

        backend = make_mock_backend(
            {
                "classify": [
                    {
                        "action_name": "classify",
                        "record_id": "r1",
                        "disposition": "failed",
                        "reason": "err",
                    },
                ],
            }
        )

        with (
            patch("agent_actions.cli.retry.get_storage_backend", return_value=backend),
            patch("agent_actions.cli.retry.ProjectPathsFactory") as mock_paths_factory,
            patch("agent_actions.cli.retry.load_workflow") as mock_load_wf,
        ):
            mock_paths = MagicMock()
            mock_paths.io_dir = tmp_path / "agent_io"
            mock_paths_factory.create_project_paths.return_value = mock_paths

            mock_wf = MagicMock()
            mock_wf.execution_order = ["classify"]
            mock_wf.run.side_effect = RuntimeError("crash during workflow")
            mock_load_wf.return_value = mock_wf

            args = RetryCommandArgs(agent="test_wf")
            cmd = RetryCommand(args)
            cmd.console = MagicMock()

            with pytest.raises(RuntimeError, match="crash during workflow"):
                cmd.execute()

        assert manifest_file.exists()


class TestManifestRestoreOnNextInvocation:
    """Next retry detects manifest and restores dispositions."""

    def test_restores_dispositions_from_manifest(self, tmp_path: Path):
        store_dir = tmp_path / "agent_io" / "store" / "test_wf"
        store_dir.mkdir(parents=True)

        # Write a manifest as if a prior retry was interrupted
        manifest_file = _manifest_path(store_dir)
        _write_manifest(
            manifest_file,
            from_action="classify",
            record_ids=["r1"],
            downstream_actions=["classify", "enrich"],
            dispositions=[
                {
                    "action_name": "classify",
                    "record_id": "r1",
                    "disposition": "failed",
                    "reason": "API error",
                    "detail": "timeout",
                    "input_snapshot": '{"field": "val"}',
                },
                {
                    "action_name": "enrich",
                    "record_id": "r1",
                    "disposition": "exhausted",
                    "reason": "retry_exhausted",
                    "detail": None,
                    "input_snapshot": None,
                },
            ],
        )

        backend = make_mock_backend(
            {
                # After restore, failures are visible again
                "classify": [
                    {
                        "action_name": "classify",
                        "record_id": "r1",
                        "disposition": "failed",
                        "reason": "API error",
                    },
                ],
            }
        )
        set_calls: list[tuple] = []

        def track_set(*args, **kwargs):
            set_calls.append((args, kwargs))

        backend.set_disposition = MagicMock(side_effect=track_set)

        with (
            patch("agent_actions.cli.retry.get_storage_backend", return_value=backend),
            patch("agent_actions.cli.retry.ProjectPathsFactory") as mock_paths_factory,
            patch("agent_actions.cli.retry.load_workflow") as mock_load_wf,
        ):
            mock_paths = MagicMock()
            mock_paths.io_dir = tmp_path / "agent_io"
            mock_paths_factory.create_project_paths.return_value = mock_paths

            mock_wf = MagicMock()
            mock_wf.execution_order = ["classify", "enrich"]
            mock_load_wf.return_value = mock_wf

            args = RetryCommandArgs(agent="test_wf")
            cmd = RetryCommand(args)
            cmd.console = MagicMock()
            cmd.execute()

        # 2 dispositions should have been restored
        assert len(set_calls) == 2

        # First restore: classify/r1/failed
        call_args, call_kwargs = set_calls[0]
        assert call_args == ("classify", "r1", "failed")
        assert call_kwargs["reason"] == "API error"
        assert call_kwargs["detail"] == "timeout"
        assert call_kwargs["input_snapshot"] == '{"field": "val"}'

        # Second restore: enrich/r1/exhausted
        call_args, call_kwargs = set_calls[1]
        assert call_args == ("enrich", "r1", "exhausted")
        assert call_kwargs["reason"] == "retry_exhausted"

        # Manifest deleted after restore
        assert not manifest_file.exists()


class TestManifestWriteFailureAborts:
    """If manifest write fails, dispositions must NOT be cleared."""

    def test_io_error_on_manifest_write_aborts(self, tmp_path: Path):
        store_dir = tmp_path / "agent_io" / "store" / "test_wf"
        store_dir.mkdir(parents=True)

        backend = make_mock_backend(
            {
                "classify": [
                    {
                        "action_name": "classify",
                        "record_id": "r1",
                        "disposition": "failed",
                        "reason": "err",
                    },
                ],
            }
        )

        with (
            patch("agent_actions.cli.retry.get_storage_backend", return_value=backend),
            patch("agent_actions.cli.retry.ProjectPathsFactory") as mock_paths_factory,
            patch("agent_actions.cli.retry.load_workflow") as mock_load_wf,
            patch("agent_actions.cli.retry._write_manifest", side_effect=OSError("disk full")),
        ):
            mock_paths = MagicMock()
            mock_paths.io_dir = tmp_path / "agent_io"
            mock_paths_factory.create_project_paths.return_value = mock_paths

            mock_wf = MagicMock()
            mock_wf.execution_order = ["classify"]
            mock_load_wf.return_value = mock_wf

            args = RetryCommandArgs(agent="test_wf")
            cmd = RetryCommand(args)
            cmd.console = MagicMock()

            with pytest.raises(OSError, match="disk full"):
                cmd.execute()

        # clear_disposition must NOT have been called
        backend.clear_disposition.assert_not_called()


class TestNoSignalHandler:
    """The manifest approach does not use SIGINT signal handlers."""

    def test_no_signal_import(self):
        import inspect

        from agent_actions.cli import retry

        source = inspect.getsource(retry)
        assert "signal.signal" not in source
        assert "SIGINT" not in source
        assert "signal_handler" not in source
