"""Tests for UDF discovery and validation."""
import pytest
import sys
from pathlib import Path
from typing import TypedDict
import tempfile
import shutil
from agent_actions.input_loading.udf_loader import discover_udfs, validate_udf_references
from agent_actions.utilities.udf_management.udf_registry import udf_tool, clear_registry, UDF_REGISTRY
from agent_actions.utilities.udf_management.type_conversion import clear_schema_cache
from agent_actions.errors import DuplicateFunctionError, FunctionNotFoundError, UDFLoadError


# Type for tests (prefixed to avoid pytest collection)
class _TestInput(TypedDict):
    value: str


# Track modules added by tests for cleanup
_test_modules_to_clean = set()


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clear registry, schema cache, and test modules before and after each test."""
    clear_registry()
    clear_schema_cache()
    # Clean up any modules added by previous tests
    test_module_names = ['file1', 'file2', 'file3', 'test', 'test_func', 'my_udf',
                         'top_level', 'nested', 'regular', 'bad', 'no_udfs',
                         'subdir.nested', 'func1', 'func2', 'func3']
    for mod_name in test_module_names:
        if mod_name in sys.modules:
            del sys.modules[mod_name]
    yield
    clear_registry()
    clear_schema_cache()
    # Clean up again after test
    for mod_name in test_module_names:
        if mod_name in sys.modules:
            del sys.modules[mod_name]


@pytest.fixture
def temp_user_code_dir():
    """Create a temporary directory for user code."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


# Template for UDF files with required input_type
UDF_TEMPLATE = '''
from typing import TypedDict
from agent_actions import udf_tool

class Input(TypedDict):
    value: str

@udf_tool(input_type=Input)
def {func_name}(data):
    return "{return_value}"
'''

MULTI_UDF_TEMPLATE = '''
from typing import TypedDict
from agent_actions import udf_tool

class Input(TypedDict):
    value: str

@udf_tool(input_type=Input)
def func1(data):
    return "func1"

@udf_tool(input_type=Input)
def func2(data):
    return "func2"
'''


class TestDiscoverUDFs:
    """Tests for discover_udfs() function."""

    def test_discover_udfs_single_file(self, temp_user_code_dir):
        """Test discovery of a single UDF in a single file."""
        udf_file = temp_user_code_dir / 'my_udf.py'
        udf_file.write_text(UDF_TEMPLATE.format(func_name='test_function', return_value='test'))
        registry = discover_udfs(temp_user_code_dir)
        assert len(registry) == 1
        assert 'test_function' in registry
        assert registry['test_function']['function']({'value': 'x'}) == 'test'

    def test_discover_udfs_multiple_files(self, temp_user_code_dir):
        """Test discovery of UDFs across multiple files."""
        file1 = temp_user_code_dir / 'file1.py'
        file1.write_text(MULTI_UDF_TEMPLATE)
        file2 = temp_user_code_dir / 'file2.py'
        file2.write_text(UDF_TEMPLATE.format(func_name='func3', return_value='func3'))
        registry = discover_udfs(temp_user_code_dir)
        assert len(registry) == 3
        assert 'func1' in registry
        assert 'func2' in registry
        assert 'func3' in registry

    def test_discover_udfs_nested_dirs(self, temp_user_code_dir):
        """Test discovery in nested directory structures."""
        sub_dir = temp_user_code_dir / 'subdir'
        sub_dir.mkdir()
        file1 = temp_user_code_dir / 'top_level.py'
        file1.write_text(UDF_TEMPLATE.format(func_name='top_func', return_value='top'))
        file2 = sub_dir / 'nested.py'
        file2.write_text(UDF_TEMPLATE.format(func_name='nested_func', return_value='nested'))
        registry = discover_udfs(temp_user_code_dir)
        assert len(registry) == 2
        assert 'top_func' in registry
        assert 'nested_func' in registry

    def test_discover_udfs_skips_private_files(self, temp_user_code_dir):
        """Test that files starting with _ are skipped."""
        private_file = temp_user_code_dir / '_private.py'
        private_file.write_text(UDF_TEMPLATE.format(func_name='private_func', return_value='private'))
        regular_file = temp_user_code_dir / 'regular.py'
        regular_file.write_text(UDF_TEMPLATE.format(func_name='regular_func', return_value='regular'))
        registry = discover_udfs(temp_user_code_dir)
        assert len(registry) == 1
        assert 'regular_func' in registry
        assert 'private_func' not in registry

    def test_discover_udfs_handles_import_errors(self, temp_user_code_dir):
        """Test that import errors are wrapped in UDFLoadError."""
        bad_file = temp_user_code_dir / 'bad.py'
        bad_file.write_text('\nfrom agent_actions import udf_tool\n\n@udf_tool(input_type=dict)\ndef bad_func()  # Missing colon - syntax error\n    return "bad"\n')
        with pytest.raises(UDFLoadError) as exc_info:
            discover_udfs(temp_user_code_dir)
        error = exc_info.value
        assert 'bad.py' in error.context['file']
        assert 'error' in error.context

    def test_discover_udfs_adds_to_sys_path(self, temp_user_code_dir):
        """Test that user_code_path is added to sys.path."""
        import sys
        user_code_str = str(temp_user_code_dir.absolute())
        if user_code_str in sys.path:
            sys.path.remove(user_code_str)
        udf_file = temp_user_code_dir / 'test.py'
        udf_file.write_text(UDF_TEMPLATE.format(func_name='test_func', return_value='test'))
        discover_udfs(temp_user_code_dir)
        assert user_code_str in sys.path

    def test_discover_udfs_duplicate_error(self, temp_user_code_dir):
        """Test that DuplicateFunctionError is propagated."""
        file1 = temp_user_code_dir / 'file1.py'
        file1.write_text(UDF_TEMPLATE.format(func_name='duplicate_func', return_value='file1'))
        file2 = temp_user_code_dir / 'file2.py'
        file2.write_text(UDF_TEMPLATE.format(func_name='duplicate_func', return_value='file2'))
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
        nonexistent = Path('/nonexistent/path/to/code')
        with pytest.raises(UDFLoadError) as exc_info:
            discover_udfs(nonexistent)
        error = exc_info.value
        assert 'not found' in str(error).lower()
        assert str(nonexistent) in error.context['user_code_path']

    def test_discover_udfs_file_not_directory(self, temp_user_code_dir):
        """Test that passing a file instead of directory raises UDFLoadError."""
        test_file = temp_user_code_dir / 'test.py'
        test_file.write_text('# test file')
        with pytest.raises(UDFLoadError) as exc_info:
            discover_udfs(test_file)
        error = exc_info.value
        assert 'not a directory' in str(error).lower()

    def test_discover_udfs_no_udfs_in_file(self, temp_user_code_dir):
        """Test file without @udf_tool decorators is processed without errors."""
        regular_file = temp_user_code_dir / 'no_udfs.py'
        regular_file.write_text('\ndef regular_function():\n    return "not a udf"\n\nclass RegularClass:\n    pass\n')
        registry = discover_udfs(temp_user_code_dir)
        assert len(registry) == 0


class TestValidateUDFReferences:
    """Tests for validate_udf_references() function."""

    def test_validate_udf_references_success(self):
        """Test that valid references pass validation."""

        @udf_tool(input_type=_TestInput)
        def valid_func(data):
            pass
        config = {'actions': [{'impl': 'valid_func'}]}
        validate_udf_references(config)

    def test_validate_udf_references_missing(self):
        """Test that FunctionNotFoundError is raised for missing functions."""
        config = {'actions': [{'impl': 'nonexistent_func'}]}
        with pytest.raises(FunctionNotFoundError) as exc_info:
            validate_udf_references(config)
        error = exc_info.value
        assert error.context['function_name'] == 'nonexistent_func'

    def test_validate_udf_references_nested_config(self):
        """Test validation works with nested config structures."""

        @udf_tool(input_type=_TestInput)
        def nested_func(data):
            pass
        config = {'pipelines': {'main': {'actions': [{'impl': 'nested_func'}, {'steps': [{'impl': 'nested_func'}]}]}}}
        validate_udf_references(config)

    def test_validate_udf_references_list_config(self):
        """Test validation works with list-based configs."""

        @udf_tool(input_type=_TestInput)
        def list_func(data):
            pass
        config = [{'impl': 'list_func'}, {'impl': 'list_func'}]
        validate_udf_references(config)

    def test_validate_udf_references_empty_config(self):
        """Test validation with empty config."""
        config = {}
        validate_udf_references(config)

    def test_validate_udf_references_no_impl_fields(self):
        """Test validation when no impl fields present."""
        config = {'actions': [{'name': 'action1'}, {'name': 'action2'}]}
        validate_udf_references(config)
