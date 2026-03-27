"""Tests for FileWriter relative path handling."""

from unittest.mock import MagicMock

from agent_actions.output.writer import FileWriter


class TestFileWriterRelativePath:
    """Tests for relative path preservation in FileWriter."""

    def test_preserves_subdirectory_structure(self, tmp_path):
        """Should preserve subdirectory structure when output_directory is provided."""
        # Setup mock storage backend
        mock_backend = MagicMock()

        # Create nested file path
        output_dir = tmp_path / "target" / "agent_name"
        file_path = output_dir / "subdir" / "nested" / "data.json"

        writer = FileWriter(
            str(file_path),
            storage_backend=mock_backend,
            action_name="agent_name",
            output_directory=str(output_dir),
        )

        # Write data
        writer.write_target([{"key": "value"}])

        # Verify relative path includes subdirectory structure
        mock_backend.write_target.assert_called_once()
        call_args = mock_backend.write_target.call_args
        assert call_args[0][0] == "agent_name"
        assert call_args[0][1] == "subdir/nested/data.json"

    def test_uses_filename_only_without_output_directory(self, tmp_path):
        """Should use filename only when output_directory is not provided."""
        mock_backend = MagicMock()

        file_path = tmp_path / "subdir" / "data.json"

        writer = FileWriter(
            str(file_path),
            storage_backend=mock_backend,
            action_name="agent_name",
            # No output_directory provided
        )

        writer.write_target([{"key": "value"}])

        # Verify only filename is used
        call_args = mock_backend.write_target.call_args
        assert call_args[0][1] == "data.json"

    def test_handles_file_not_under_output_directory(self, tmp_path):
        """Should fall back to filename when file is not under output_directory."""
        mock_backend = MagicMock()

        output_dir = tmp_path / "output"
        file_path = tmp_path / "other" / "data.json"  # Not under output_dir

        writer = FileWriter(
            str(file_path),
            storage_backend=mock_backend,
            action_name="agent_name",
            output_directory=str(output_dir),
        )

        writer.write_target([{"key": "value"}])

        # Verify falls back to filename only
        call_args = mock_backend.write_target.call_args
        assert call_args[0][1] == "data.json"

    def test_prevents_collision_for_same_filename_different_dirs(self, tmp_path):
        """Should prevent collision when same filename exists in different subdirs."""
        mock_backend = MagicMock()

        output_dir = tmp_path / "target" / "agent_name"

        # Write first file
        file_path_a = output_dir / "a" / "data.json"
        writer_a = FileWriter(
            str(file_path_a),
            storage_backend=mock_backend,
            action_name="agent_name",
            output_directory=str(output_dir),
        )
        writer_a.write_target([{"source": "a"}])

        # Write second file with same name in different subdir
        file_path_b = output_dir / "b" / "data.json"
        writer_b = FileWriter(
            str(file_path_b),
            storage_backend=mock_backend,
            action_name="agent_name",
            output_directory=str(output_dir),
        )
        writer_b.write_target([{"source": "b"}])

        # Verify different relative paths were used
        calls = mock_backend.write_target.call_args_list
        assert len(calls) == 2
        assert calls[0][0][1] == "a/data.json"
        assert calls[1][0][1] == "b/data.json"
