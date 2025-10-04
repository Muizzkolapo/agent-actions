"""Tests for list-udfs CLI command."""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
import tempfile
import shutil

from agent_actions.tasks.list_udfs import list_udfs_cmd
from agent_actions.core.udf_registry import clear_registry


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clear registry before and after each test."""
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def temp_user_code_dir():
    """Create a temporary directory for user code."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def runner():
    """Create Click CLI test runner."""
    return CliRunner()


class TestListUDFsCommand:
    """Tests for list-udfs command."""

    def test_list_udfs_table_format(self, runner, temp_user_code_dir):
        """Test list-udfs displays UDFs in table format."""
        # Create UDF file
        udf_file = temp_user_code_dir / "my_functions.py"
        udf_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def test_function():
    '''Test function docstring.'''
    return "test"

@udf_tool
def another_function():
    '''Another test function.'''
    return "another"
""")

        result = runner.invoke(list_udfs_cmd, ['-u', str(temp_user_code_dir)])

        assert result.exit_code == 0
        assert '🔍 Discovering UDFs' in result.output
        assert '✅ Discovered 2 UDF(s)' in result.output
        assert 'test_function' in result.output
        assert 'another_function' in result.output
        assert 'Total: 2 function(s)' in result.output

    def test_list_udfs_json_format(self, runner, temp_user_code_dir):
        """Test list-udfs outputs JSON when --json flag is used."""
        # Create UDF file
        udf_file = temp_user_code_dir / "functions.py"
        udf_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def json_test_function(data):
    '''Test function for JSON output.'''
    return data
""")

        result = runner.invoke(list_udfs_cmd, ['-u', str(temp_user_code_dir), '--json'])

        assert result.exit_code == 0

        # Parse JSON output
        output = json.loads(result.output)
        assert isinstance(output, list)
        assert len(output) == 1
        assert output[0]['name'] == 'json_test_function'
        assert output[0]['module'] == 'functions'
        assert 'file' in output[0]
        assert output[0]['signature'] == '(data)'

    def test_list_udfs_verbose(self, runner, temp_user_code_dir):
        """Test list-udfs shows full details with --verbose flag."""
        # Create UDF file
        udf_file = temp_user_code_dir / "verbose_funcs.py"
        udf_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def verbose_function(x, y):
    '''
    Multi-line docstring.

    This function does something verbose.
    '''
    return x + y
""")

        result = runner.invoke(list_udfs_cmd, ['-u', str(temp_user_code_dir), '--verbose'])

        assert result.exit_code == 0
        assert 'verbose_function' in result.output
        assert 'Signature' in result.output or '(x, y)' in result.output
        assert 'Description' in result.output or 'Multi-line docstring' in result.output

    def test_list_udfs_empty_registry(self, runner, temp_user_code_dir):
        """Test list-udfs handles empty directory gracefully."""
        # Create empty directory (or with non-UDF Python file)
        regular_file = temp_user_code_dir / "regular.py"
        regular_file.write_text("""
def regular_function():
    return "not a udf"
""")

        result = runner.invoke(list_udfs_cmd, ['-u', str(temp_user_code_dir)])

        assert result.exit_code == 0
        assert 'No UDFs found' in result.output or 'Discovered 0 UDF(s)' in result.output

    def test_list_udfs_with_metadata(self, runner, temp_user_code_dir):
        """Test list-udfs displays correct metadata for UDFs."""
        # Create UDF with detailed metadata
        udf_file = temp_user_code_dir / "metadata_test.py"
        udf_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def function_with_metadata(param1, param2):
    '''Process data with two parameters.'''
    return param1 + param2
""")

        result = runner.invoke(list_udfs_cmd, ['-u', str(temp_user_code_dir)])

        assert result.exit_code == 0
        assert 'function_with_metadata' in result.output
        assert 'metadata_test' in result.output  # Module name
        # Path might be truncated in table, just check module is there
        assert 'Process data with two parameters' in result.output  # Docstring

    def test_list_udfs_json_verbose(self, runner, temp_user_code_dir):
        """Test list-udfs JSON output includes docstrings with --verbose."""
        # Create UDF file
        udf_file = temp_user_code_dir / "doc_test.py"
        udf_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def documented_function():
    '''This is a documented function.'''
    return "doc"
""")

        result = runner.invoke(list_udfs_cmd, [
            '-u', str(temp_user_code_dir),
            '--json',
            '--verbose'
        ])

        assert result.exit_code == 0

        output = json.loads(result.output)
        assert len(output) == 1
        assert 'docstring' in output[0]
        assert 'documented function' in output[0]['docstring'].lower()

    def test_list_udfs_nonexistent_directory(self, runner):
        """Test list-udfs handles nonexistent directory error."""
        result = runner.invoke(list_udfs_cmd, ['-u', '/nonexistent/path'])

        assert result.exit_code != 0
        # Click will handle the path validation error

    def test_list_udfs_nested_directories(self, runner, temp_user_code_dir):
        """Test list-udfs discovers UDFs in nested directories."""
        # Create nested structure
        sub_dir = temp_user_code_dir / "subdir"
        sub_dir.mkdir()

        file1 = temp_user_code_dir / "top.py"
        file1.write_text("""
from agent_actions import udf_tool

@udf_tool
def top_level():
    return "top"
""")

        file2 = sub_dir / "nested.py"
        file2.write_text("""
from agent_actions import udf_tool

@udf_tool
def nested_level():
    return "nested"
""")

        result = runner.invoke(list_udfs_cmd, ['-u', str(temp_user_code_dir)])

        assert result.exit_code == 0
        assert 'Discovered 2 UDF(s)' in result.output
        assert 'top_level' in result.output
        assert 'nested_level' in result.output
