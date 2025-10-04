"""Tests for UDF discovery and validation."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import shutil

from agent_actions.core.udf_loader import (
    discover_udfs,
    validate_udf_references
)
from agent_actions.core.udf_registry import (
    udf_tool,
    clear_registry,
    UDF_REGISTRY
)
from agent_actions.core.exceptions import (
    DuplicateFunctionError,
    FunctionNotFoundError,
    UDFLoadError
)


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clear registry before and after each test for isolation."""
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def temp_user_code_dir():
    """Create a temporary directory for user code."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    # Cleanup
    shutil.rmtree(temp_dir)


class TestDiscoverUDFs:
    """Tests for discover_udfs() function."""

    def test_discover_udfs_single_file(self, temp_user_code_dir):
        """Test discovery of a single UDF in a single file."""
        # Create a Python file with one UDF
        udf_file = temp_user_code_dir / "my_udf.py"
        udf_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def test_function():
    return "test"
""")

        registry = discover_udfs(temp_user_code_dir)

        assert len(registry) == 1
        assert 'test_function' in registry
        assert registry['test_function']['function']() == "test"

    def test_discover_udfs_multiple_files(self, temp_user_code_dir):
        """Test discovery of UDFs across multiple files."""
        # Create multiple files with UDFs
        file1 = temp_user_code_dir / "file1.py"
        file1.write_text("""
from agent_actions import udf_tool

@udf_tool
def func1():
    return "func1"

@udf_tool
def func2():
    return "func2"
""")

        file2 = temp_user_code_dir / "file2.py"
        file2.write_text("""
from agent_actions import udf_tool

@udf_tool
def func3():
    return "func3"
""")

        registry = discover_udfs(temp_user_code_dir)

        assert len(registry) == 3
        assert 'func1' in registry
        assert 'func2' in registry
        assert 'func3' in registry

    def test_discover_udfs_nested_dirs(self, temp_user_code_dir):
        """Test discovery in nested directory structures."""
        # Create nested directories
        sub_dir = temp_user_code_dir / "subdir"
        sub_dir.mkdir()

        file1 = temp_user_code_dir / "top_level.py"
        file1.write_text("""
from agent_actions import udf_tool

@udf_tool
def top_func():
    return "top"
""")

        file2 = sub_dir / "nested.py"
        file2.write_text("""
from agent_actions import udf_tool

@udf_tool
def nested_func():
    return "nested"
""")

        registry = discover_udfs(temp_user_code_dir)

        assert len(registry) == 2
        assert 'top_func' in registry
        assert 'nested_func' in registry

    def test_discover_udfs_skips_private_files(self, temp_user_code_dir):
        """Test that files starting with _ are skipped."""
        # Create a private file (should be skipped)
        private_file = temp_user_code_dir / "_private.py"
        private_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def private_func():
    return "private"
""")

        # Create a regular file (should be discovered)
        regular_file = temp_user_code_dir / "regular.py"
        regular_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def regular_func():
    return "regular"
""")

        registry = discover_udfs(temp_user_code_dir)

        assert len(registry) == 1
        assert 'regular_func' in registry
        assert 'private_func' not in registry

    def test_discover_udfs_handles_import_errors(self, temp_user_code_dir):
        """Test that import errors are wrapped in UDFLoadError."""
        # Create a file with syntax error
        bad_file = temp_user_code_dir / "bad.py"
        bad_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def bad_func()  # Missing colon - syntax error
    return "bad"
""")

        with pytest.raises(UDFLoadError) as exc_info:
            discover_udfs(temp_user_code_dir)

        error = exc_info.value
        assert 'bad.py' in error.context['file']
        assert 'error' in error.context

    def test_discover_udfs_adds_to_sys_path(self, temp_user_code_dir):
        """Test that user_code_path is added to sys.path."""
        import sys

        user_code_str = str(temp_user_code_dir.absolute())

        # Ensure not in sys.path initially
        if user_code_str in sys.path:
            sys.path.remove(user_code_str)

        # Create a simple UDF file
        udf_file = temp_user_code_dir / "test.py"
        udf_file.write_text("""
from agent_actions import udf_tool

@udf_tool
def test_func():
    return "test"
""")

        discover_udfs(temp_user_code_dir)

        assert user_code_str in sys.path

    def test_discover_udfs_duplicate_error(self, temp_user_code_dir):
        """Test that DuplicateFunctionError is propagated."""
        # Create two files with same function name
        file1 = temp_user_code_dir / "file1.py"
        file1.write_text("""
from agent_actions import udf_tool

@udf_tool
def duplicate_func():
    return "file1"
""")

        file2 = temp_user_code_dir / "file2.py"
        file2.write_text("""
from agent_actions import udf_tool

@udf_tool
def duplicate_func():
    return "file2"
""")

        with pytest.raises(DuplicateFunctionError) as exc_info:
            discover_udfs(temp_user_code_dir)

        error = exc_info.value
        assert error.context['function_name'] == 'duplicate_func'

    def test_discover_udfs_empty_dir(self, temp_user_code_dir):
        """Test discovery in empty directory returns empty registry."""
        registry = discover_udfs(temp_user_code_dir)

        assert len(registry) == 0

    def test_discover_udfs_nonexistent_path(self):
        """Test that nonexistent path raises UDFLoadError."""
        nonexistent = Path("/nonexistent/path/to/code")

        with pytest.raises(UDFLoadError) as exc_info:
            discover_udfs(nonexistent)

        error = exc_info.value
        assert 'not found' in str(error).lower()
        assert str(nonexistent) in error.context['user_code_path']

    def test_discover_udfs_file_not_directory(self, temp_user_code_dir):
        """Test that passing a file instead of directory raises UDFLoadError."""
        # Create a file
        test_file = temp_user_code_dir / "test.py"
        test_file.write_text("# test file")

        with pytest.raises(UDFLoadError) as exc_info:
            discover_udfs(test_file)

        error = exc_info.value
        assert 'not a directory' in str(error).lower()

    def test_discover_udfs_no_udfs_in_file(self, temp_user_code_dir):
        """Test file without @udf_tool decorators is processed without errors."""
        # Create a file with no UDFs
        regular_file = temp_user_code_dir / "no_udfs.py"
        regular_file.write_text("""
def regular_function():
    return "not a udf"

class RegularClass:
    pass
""")

        registry = discover_udfs(temp_user_code_dir)

        assert len(registry) == 0


class TestValidateUDFReferences:
    """Tests for validate_udf_references() function."""

    def test_validate_udf_references_success(self):
        """Test that valid references pass validation."""
        @udf_tool
        def valid_func():
            pass

        config = {
            'actions': [
                {'impl': 'valid_func'}
            ]
        }

        # Should not raise
        validate_udf_references(config)

    def test_validate_udf_references_missing(self):
        """Test that FunctionNotFoundError is raised for missing functions."""
        config = {
            'actions': [
                {'impl': 'nonexistent_func'}
            ]
        }

        with pytest.raises(FunctionNotFoundError) as exc_info:
            validate_udf_references(config)

        error = exc_info.value
        assert error.context['function_name'] == 'nonexistent_func'

    def test_validate_udf_references_nested_config(self):
        """Test validation works with nested config structures."""
        @udf_tool
        def nested_func():
            pass

        config = {
            'pipelines': {
                'main': {
                    'actions': [
                        {'impl': 'nested_func'},
                        {
                            'steps': [
                                {'impl': 'nested_func'}
                            ]
                        }
                    ]
                }
            }
        }

        # Should not raise
        validate_udf_references(config)

    def test_validate_udf_references_list_config(self):
        """Test validation works with list-based configs."""
        @udf_tool
        def list_func():
            pass

        config = [
            {'impl': 'list_func'},
            {'impl': 'list_func'}
        ]

        # Should not raise
        validate_udf_references(config)

    def test_validate_udf_references_empty_config(self):
        """Test validation with empty config."""
        config = {}

        # Should not raise
        validate_udf_references(config)

    def test_validate_udf_references_no_impl_fields(self):
        """Test validation when no impl fields present."""
        config = {
            'actions': [
                {'name': 'action1'},
                {'name': 'action2'}
            ]
        }

        # Should not raise
        validate_udf_references(config)
