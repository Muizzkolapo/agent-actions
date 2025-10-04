"""
Comprehensive status task tests for the Agent Actions status command.

Tests cover status task functionality as specified in tests_recommendations.jsonc:
1. Reads artifacts safely and summarizes status
2. Handles missing/stale/partial data gracefully
"""

import json
import pytest
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock, patch, mock_open
from click.testing import CliRunner

from agent_actions.tasks.status import StatusCommand, status
from agent_actions.agents.validators.status_validator import StatusCommandArgs
from pydantic import ValidationError as PydanticValidationError


class TestStatusCommandArgs:
    """Test StatusCommandArgs pydantic model."""

    def test_valid_status_command_args(self):
        """Test valid StatusCommandArgs creation."""
        args = StatusCommandArgs(agent="test_agent")

        assert args.agent == "test_agent"

    def test_status_command_args_validation_empty_agent(self):
        """Test StatusCommandArgs validation rejects empty agent name."""
        with pytest.raises(PydanticValidationError):
            StatusCommandArgs(agent="")

    def test_status_command_args_missing_agent(self):
        """Test StatusCommandArgs validation requires agent."""
        with pytest.raises(PydanticValidationError):
            StatusCommandArgs()

    def test_status_command_args_with_path_extension(self):
        """Test StatusCommandArgs accepts agent with path and extension."""
        args = StatusCommandArgs(agent="path/to/agent.yml")

        assert args.agent == "path/to/agent.yml"


class TestStatusCommand:
    """Test StatusCommand implementation."""

    def test_status_command_initialization(self):
        """Test StatusCommand initialization."""
        args = StatusCommandArgs(agent="test_agent")

        with patch('agent_actions.tasks.status.Console') as mock_console_class:
            mock_console = Mock()
            mock_console_class.return_value = mock_console

            command = StatusCommand(args)

            assert command.args == args
            assert command.agent_name == "test_agent"
            assert command.console == mock_console

    def test_status_command_initialization_with_path(self):
        """Test StatusCommand initialization with agent path."""
        args = StatusCommandArgs(agent="path/to/complex_agent.yml")

        with patch('agent_actions.tasks.status.Console'):
            command = StatusCommand(args)

            # Should extract stem from path
            assert command.agent_name == "complex_agent"

    def test_execute_success_with_status_file(self, tmp_path):
        """Test successful execution with existing status file."""
        args = StatusCommandArgs(agent="success_agent")

        # Create mock status data
        status_data = {
            "agent1": {"status": "completed", "last_run": "2024-01-01T10:00:00"},
            "agent2": {"status": "running", "last_run": "2024-01-01T11:00:00"},
            "agent3": {"status": "failed", "last_run": "2024-01-01T09:00:00"}
        }

        # Mock project paths
        mock_paths = Mock()
        mock_paths.agent_io_dir = tmp_path / "io"
        mock_paths.agent_io_dir.mkdir(parents=True)

        status_file = mock_paths.agent_io_dir / ".agent_status.json"
        status_file.write_text(json.dumps(status_data))

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console') as mock_console_class:
                mock_console = Mock()
                mock_console_class.return_value = mock_console

                command = StatusCommand(args)
                command.execute()

                # Verify console output was called
                mock_console.print.assert_called()
                # Should have printed a table
                print_calls = mock_console.print.call_args_list
                assert len(print_calls) > 0

    def test_execute_no_status_file_found(self, tmp_path):
        """Test execution when no status file is found."""
        args = StatusCommandArgs(agent="missing_agent")

        # Mock project paths without creating status file
        mock_paths = Mock()
        mock_paths.agent_io_dir = tmp_path / "io"
        mock_paths.agent_io_dir.mkdir(parents=True)

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console') as mock_console_class:
                mock_console = Mock()
                mock_console_class.return_value = mock_console

                command = StatusCommand(args)
                command.execute()

                # Should print warning message about missing status file
                mock_console.print.assert_called_once()
                warning_message = mock_console.print.call_args[0][0]
                assert "No status file found" in warning_message
                assert "missing_agent" in warning_message

    def test_execute_handles_missing_data_gracefully(self, tmp_path):
        """Test handles missing/stale/partial data gracefully."""
        args = StatusCommandArgs(agent="partial_agent")

        # Create status data with missing/partial information
        partial_status_data = {
            "agent1": {"status": "completed"},  # Missing last_run
            "agent2": {},  # Missing status
            "agent3": {"status": "unknown", "extra_field": "value"},  # Extra fields
            "agent4": None,  # Null entry
        }

        mock_paths = Mock()
        mock_paths.agent_io_dir = tmp_path / "io"
        mock_paths.agent_io_dir.mkdir(parents=True)

        status_file = mock_paths.agent_io_dir / ".agent_status.json"
        status_file.write_text(json.dumps(partial_status_data))

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console') as mock_console_class:
                mock_console = Mock()
                mock_console_class.return_value = mock_console

                command = StatusCommand(args)
                command.execute()

                # Should execute without errors and display available data
                mock_console.print.assert_called()

    def test_execute_handles_corrupted_json_gracefully(self, tmp_path):
        """Test handles corrupted JSON data gracefully."""
        args = StatusCommandArgs(agent="corrupted_agent")

        mock_paths = Mock()
        mock_paths.agent_io_dir = tmp_path / "io"
        mock_paths.agent_io_dir.mkdir(parents=True)

        # Create corrupted JSON file
        status_file = mock_paths.agent_io_dir / ".agent_status.json"
        status_file.write_text('{"invalid": json, "syntax": error}')

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console'):
                command = StatusCommand(args)

                # Should raise ClickException with helpful error
                with pytest.raises(Exception) as exc_info:
                    command.execute()

                assert "Failed to get status" in str(exc_info.value) or \
                       "ClickException" in str(type(exc_info.value))

    def test_execute_handles_empty_status_file(self, tmp_path):
        """Test handles empty status file gracefully."""
        args = StatusCommandArgs(agent="empty_agent")

        mock_paths = Mock()
        mock_paths.agent_io_dir = tmp_path / "io"
        mock_paths.agent_io_dir.mkdir(parents=True)

        # Create empty status file
        status_file = mock_paths.agent_io_dir / ".agent_status.json"
        status_file.write_text('{}')

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console') as mock_console_class:
                mock_console = Mock()
                mock_console_class.return_value = mock_console

                command = StatusCommand(args)
                command.execute()

                # Should display empty table without errors
                mock_console.print.assert_called()

    def test_execute_permission_error(self, tmp_path):
        """Test execution handles permission errors gracefully."""
        args = StatusCommandArgs(agent="permission_agent")

        mock_paths = Mock()
        mock_paths.agent_io_dir = tmp_path / "io"

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            # Mock file read to raise permission error
            with patch('builtins.open', side_effect=PermissionError("Permission denied")):
                # Mock file existence to return True so we get to the file read
                with patch('pathlib.Path.exists', return_value=True):
                    with patch('agent_actions.tasks.status.Console'):
                        command = StatusCommand(args)

                        with pytest.raises(Exception) as exc_info:
                            command.execute()

                        assert "Failed to get status" in str(exc_info.value) or \
                               "ClickException" in str(type(exc_info.value))

    def test_execute_project_paths_factory_error(self):
        """Test execution handles ProjectPathsFactory errors."""
        args = StatusCommandArgs(agent="factory_error_agent")

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.side_effect = Exception("Project paths creation failed")

            with patch('agent_actions.tasks.status.Console'):
                command = StatusCommand(args)

                with pytest.raises(Exception) as exc_info:
                    command.execute()

                assert "Failed to get status" in str(exc_info.value) or \
                       "ClickException" in str(type(exc_info.value))


class TestStatusCommandDataHandling:
    """Test status command data reading and processing."""

    def test_reads_artifacts_safely_and_summarizes_status(self, tmp_path):
        """Test reads artifacts safely and summarizes status."""
        args = StatusCommandArgs(agent="safe_read_agent")

        # Create comprehensive status data
        comprehensive_status = {
            "data_extractor": {
                "status": "completed",
                "last_run": "2024-01-01T10:00:00",
                "items_processed": 100,
                "execution_time": "2.5s"
            },
            "data_transformer": {
                "status": "running",
                "last_run": "2024-01-01T10:30:00",
                "progress": "50%"
            },
            "data_validator": {
                "status": "pending",
                "last_run": None,
                "queue_position": 3
            }
        }

        mock_paths = Mock()
        mock_paths.agent_io_dir = tmp_path / "io"
        mock_paths.agent_io_dir.mkdir(parents=True)

        status_file = mock_paths.agent_io_dir / ".agent_status.json"
        status_file.write_text(json.dumps(comprehensive_status))

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console') as mock_console_class:
                mock_console = Mock()
                mock_table = Mock()
                mock_console_class.return_value = mock_console

                with patch('agent_actions.tasks.status.Table') as mock_table_class:
                    mock_table_class.return_value = mock_table

                    command = StatusCommand(args)
                    command.execute()

                    # Verify table was created with proper title
                    mock_table_class.assert_called_once_with(title="Workflow Status for safe_read_agent")

                    # Verify columns were added
                    assert mock_table.add_column.call_count == 2
                    column_calls = mock_table.add_column.call_args_list
                    assert "Agent Name" in column_calls[0][0][0]
                    assert "Status" in column_calls[1][0][0]

                    # Verify rows were added for each agent
                    assert mock_table.add_row.call_count == 3
                    row_calls = mock_table.add_row.call_args_list
                    assert ("data_extractor", "completed") == row_calls[0][0]
                    assert ("data_transformer", "running") == row_calls[1][0]
                    assert ("data_validator", "pending") == row_calls[2][0]

                    # Verify table was printed
                    mock_console.print.assert_called_once_with(mock_table)

    def test_handles_stale_data_gracefully(self, tmp_path):
        """Test handles stale data gracefully."""
        args = StatusCommandArgs(agent="stale_data_agent")

        # Create status data that might be considered stale
        stale_status = {
            "old_agent": {
                "status": "completed",
                "last_run": "2020-01-01T00:00:00",  # Very old timestamp
                "version": "1.0"  # Old version
            },
            "deprecated_agent": {
                "status": "deprecated",
                "replacement": "new_agent"
            }
        }

        mock_paths = Mock()
        mock_paths.agent_io_dir = tmp_path / "io"
        mock_paths.agent_io_dir.mkdir(parents=True)

        status_file = mock_paths.agent_io_dir / ".agent_status.json"
        status_file.write_text(json.dumps(stale_status))

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console') as mock_console_class:
                mock_console = Mock()
                mock_console_class.return_value = mock_console

                command = StatusCommand(args)
                command.execute()

                # Should display the data as-is without errors
                mock_console.print.assert_called()

    def test_handles_malformed_status_entries(self, tmp_path):
        """Test handles malformed status entries gracefully."""
        args = StatusCommandArgs(agent="malformed_agent")

        # Create status data with various malformed entries
        malformed_status = {
            "string_status": "just a string",  # Not a dict
            "number_status": 42,  # Not a dict
            "array_status": ["status1", "status2"],  # Not a dict
            "valid_agent": {"status": "completed"},  # Valid entry
            "null_status": None,  # Null entry
        }

        mock_paths = Mock()
        mock_paths.agent_io_dir = tmp_path / "io"
        mock_paths.agent_io_dir.mkdir(parents=True)

        status_file = mock_paths.agent_io_dir / ".agent_status.json"
        status_file.write_text(json.dumps(malformed_status))

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console') as mock_console_class:
                mock_console = Mock()
                mock_console_class.return_value = mock_console

                command = StatusCommand(args)

                # Should handle malformed entries gracefully
                try:
                    command.execute()
                    mock_console.print.assert_called()
                except Exception as e:
                    # Should provide helpful error message
                    assert "Failed to get status" in str(e)

    def test_handles_unicode_and_special_characters(self, tmp_path):
        """Test handles unicode and special characters in status data."""
        args = StatusCommandArgs(agent="unicode_agent")

        # Create status data with unicode and special characters
        unicode_status = {
            "agent_ñame": {"status": "completed", "message": "Ñice work! 🎉"},
            "测试代理": {"status": "running", "description": "测试描述"},
            "agent@special!chars": {"status": "failed", "error": "Spëcial €rror"}
        }

        mock_paths = Mock()
        mock_paths.agent_io_dir = tmp_path / "io"
        mock_paths.agent_io_dir.mkdir(parents=True)

        status_file = mock_paths.agent_io_dir / ".agent_status.json"
        status_file.write_text(json.dumps(unicode_status, ensure_ascii=False), encoding='utf-8')

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console') as mock_console_class:
                mock_console = Mock()
                mock_console_class.return_value = mock_console

                command = StatusCommand(args)
                command.execute()

                # Should handle unicode characters without errors
                mock_console.print.assert_called()


class TestStatusClickCommand:
    """Test the Click command interface for status."""

    def test_status_click_command_success(self, tmp_path):
        """Test status Click command executes successfully."""
        runner = CliRunner()

        with patch('agent_actions.tasks.status.StatusCommand') as mock_command_class:
            mock_command = Mock()
            mock_command_class.return_value = mock_command

            with runner.isolated_filesystem():
                Path('agent_actions.yml').write_text('# Test project')

                result = runner.invoke(status, ['--agent', 'test_agent'])

                assert result.exit_code == 0
                mock_command_class.assert_called_once()
                mock_command.execute.assert_called_once()

    def test_status_click_command_short_option(self):
        """Test status Click command with short option."""
        runner = CliRunner()

        with patch('agent_actions.tasks.status.StatusCommand') as mock_command_class:
            mock_command = Mock()
            mock_command_class.return_value = mock_command

            with runner.isolated_filesystem():
                Path('agent_actions.yml').write_text('# Test project')

                result = runner.invoke(status, ['-a', 'short_test'])

                assert result.exit_code == 0
                # Verify correct argument was passed
                args_call = mock_command_class.call_args[0][0]
                assert args_call.agent == "short_test"

    def test_status_click_command_required_agent(self):
        """Test status Click command requires agent parameter."""
        runner = CliRunner()

        result = runner.invoke(status, [])

        assert result.exit_code != 0
        assert "agent" in result.output.lower() or "required" in result.output.lower()

    def test_status_click_command_validation_error(self):
        """Test status Click command handles validation errors."""
        runner = CliRunner()

        # Mock StatusCommandArgs to raise validation error
        def mock_status(*args, **kwargs):
            try:
                from agent_actions.agents.validators.status_validator import StatusCommandArgs
                return StatusCommandArgs(agent="")  # This will raise ValidationError
            except PydanticValidationError as e:
                raise e

        with patch('agent_actions.tasks.status.StatusCommandArgs', side_effect=mock_status):

            with runner.isolated_filesystem():
                Path('agent_actions.yml').write_text('# Test project')

                result = runner.invoke(status, ['--agent', ''])

                assert result.exit_code != 0
                assert "Error" in result.output

    def test_status_click_command_execution_error(self):
        """Test status Click command handles execution errors."""
        runner = CliRunner()

        with patch('agent_actions.tasks.status.StatusCommand') as mock_command_class:
            mock_command = Mock()
            mock_command.execute.side_effect = Exception("Status execution failed")
            mock_command_class.return_value = mock_command

            with runner.isolated_filesystem():
                Path('agent_actions.yml').write_text('# Test project')

                result = runner.invoke(status, ['--agent', 'error_test'])

                assert result.exit_code != 0

    def test_status_click_command_help(self):
        """Test status Click command help display."""
        runner = CliRunner()

        result = runner.invoke(status, ['--help'])

        assert result.exit_code == 0
        assert 'Display the status of an agent workflow' in result.output
        assert '--agent' in result.output


class TestStatusCommandIntegration:
    """Integration tests for status command functionality."""

    def test_end_to_end_status_command(self, tmp_path):
        """Test end-to-end status command with minimal mocking."""
        # Setup test environment
        io_dir = tmp_path / "io"
        io_dir.mkdir()

        status_data = {
            "integration_agent": {
                "status": "completed",
                "last_run": "2024-01-01T12:00:00",
                "duration": "5.2s"
            }
        }

        status_file = io_dir / ".agent_status.json"
        status_file.write_text(json.dumps(status_data))

        args = StatusCommandArgs(agent="integration_test")

        # Mock only the external dependencies
        mock_paths = Mock()
        mock_paths.agent_io_dir = io_dir

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console') as mock_console_class:
                mock_console = Mock()
                mock_console_class.return_value = mock_console

                command = StatusCommand(args)
                command.execute()

                # Should execute without errors
                mock_console.print.assert_called()

    def test_status_command_with_multiple_agents(self, tmp_path):
        """Test status command with multiple agents in status file."""
        # Create status data for multiple agents
        multi_agent_status = {
            f"agent_{i}": {
                "status": ["pending", "running", "completed", "failed"][i % 4],
                "last_run": f"2024-01-01T{10+i:02d}:00:00",
                "items": i * 10
            }
            for i in range(10)
        }

        io_dir = tmp_path / "io"
        io_dir.mkdir()

        status_file = io_dir / ".agent_status.json"
        status_file.write_text(json.dumps(multi_agent_status))

        args = StatusCommandArgs(agent="multi_agent_test")

        mock_paths = Mock()
        mock_paths.agent_io_dir = io_dir

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console') as mock_console_class:
                mock_console = Mock()
                mock_table = Mock()
                mock_console_class.return_value = mock_console

                with patch('agent_actions.tasks.status.Table') as mock_table_class:
                    mock_table_class.return_value = mock_table

                    command = StatusCommand(args)
                    command.execute()

                    # Should handle all agents
                    assert mock_table.add_row.call_count == 10

    def test_status_command_concurrent_access(self, tmp_path):
        """Test status command handles concurrent access to status file."""
        args = StatusCommandArgs(agent="concurrent_test")

        mock_paths = Mock()
        mock_paths.agent_io_dir = tmp_path / "io"
        mock_paths.agent_io_dir.mkdir()

        status_file = mock_paths.agent_io_dir / ".agent_status.json"
        status_file.write_text('{"agent": {"status": "running"}}')

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            # Simulate file being locked/busy
            with patch('builtins.open', side_effect=OSError("Resource temporarily unavailable")):
                with patch('agent_actions.tasks.status.Console'):
                    command = StatusCommand(args)

                    with pytest.raises(Exception) as exc_info:
                        command.execute()

                    # Should provide helpful error message
                    assert "Failed to get status" in str(exc_info.value) or \
                           "ClickException" in str(type(exc_info.value))

    def test_status_command_large_status_file(self, tmp_path):
        """Test status command handles large status files efficiently."""
        # Create large status data
        large_status = {
            f"agent_{i}": {
                "status": "completed",
                "data": f"large data chunk {i}" * 100  # Simulate large data
            }
            for i in range(1000)  # 1000 agents
        }

        io_dir = tmp_path / "io"
        io_dir.mkdir()

        status_file = io_dir / ".agent_status.json"
        status_file.write_text(json.dumps(large_status))

        args = StatusCommandArgs(agent="large_file_test")

        mock_paths = Mock()
        mock_paths.agent_io_dir = io_dir

        with patch('agent_actions.tasks.status.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths

            with patch('agent_actions.tasks.status.Console') as mock_console_class:
                mock_console = Mock()
                mock_console_class.return_value = mock_console

                command = StatusCommand(args)

                # Should handle large file without memory issues
                command.execute()
                mock_console.print.assert_called()