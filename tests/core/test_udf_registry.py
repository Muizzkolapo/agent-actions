"""Tests for UDF registry and @udf_tool decorator."""
import pytest
from pathlib import Path
from typing import TypedDict
from agent_actions.utilities.udf_management.udf_registry import udf_tool, get_udf, list_udfs, clear_registry, UDF_REGISTRY
from agent_actions.errors import DuplicateFunctionError, FunctionNotFoundError


# Default test type for tests that don't care about schema content
class SimpleInput(TypedDict):
    text: str


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clear registry before and after each test for isolation."""
    clear_registry()
    yield
    clear_registry()


class TestUDFRegistration:
    """Tests for @udf_tool decorator registration."""

    def test_udf_registration(self):
        """Test that @udf_tool decorator registers function in registry."""

        @udf_tool(input_type=SimpleInput)
        def test_function():
            """Test docstring."""
            return 'test'
        assert 'test_function' in UDF_REGISTRY
        assert UDF_REGISTRY['test_function']['name'] == 'test_function'
        assert UDF_REGISTRY['test_function']['function']() == 'test'

    def test_duplicate_udf_raises_error(self):
        """Test that duplicate function names raise DuplicateFunctionError."""

        @udf_tool(input_type=SimpleInput)
        def duplicate_func():
            pass
        with pytest.raises(DuplicateFunctionError) as exc_info:

            @udf_tool(input_type=SimpleInput)
            def duplicate_func():  # noqa: F811
                pass
        error = exc_info.value
        assert error.context['function_name'] == 'duplicate_func'
        assert 'existing_location' in error.context
        assert 'new_location' in error.context
        assert 'existing_file' in error.context
        assert 'new_file' in error.context

    def test_registry_stores_metadata(self):
        """Test that all metadata is captured and stored."""

        @udf_tool(input_type=SimpleInput)
        def metadata_func(x, y):
            """Function with metadata."""
            return x + y
        meta = UDF_REGISTRY['metadata_func']
        assert meta['function'] == metadata_func
        assert meta['name'] == 'metadata_func'
        assert 'test_udf_registry' in meta['module']
        assert meta['docstring'] == 'Function with metadata.'
        assert 'file' in meta
        assert 'signature' in meta
        assert str(meta['signature']) == '(x, y)'

    def test_decorator_preserves_function(self):
        """Test that decorator returns original function unchanged."""

        @udf_tool(input_type=SimpleInput)
        def preserved_func(a, b):
            """Original docstring."""
            return a * b
        assert preserved_func(3, 4) == 12
        assert preserved_func.__name__ == 'preserved_func'
        assert preserved_func.__doc__ == 'Original docstring.'

    def test_case_insensitive_duplicate_detection(self):
        """Test that duplicate detection is case-insensitive."""

        @udf_tool(input_type=SimpleInput)
        def My_Function():
            pass
        with pytest.raises(DuplicateFunctionError):

            @udf_tool(input_type=SimpleInput)
            def my_function():  # noqa: F811
                pass


class TestUDFRetrieval:
    """Tests for get_udf() function."""

    def test_get_udf_retrieves_function(self):
        """Test that get_udf() retrieves registered function."""

        @udf_tool(input_type=SimpleInput)
        def retrieve_test():
            return 'retrieved'
        func = get_udf('retrieve_test')
        assert func() == 'retrieved'

    def test_get_udf_case_insensitive(self):
        """Test that get_udf() is case-insensitive."""

        @udf_tool(input_type=SimpleInput)
        def CaseSensitive():
            return 'result'
        assert get_udf('CaseSensitive')() == 'result'
        assert get_udf('casesensitive')() == 'result'
        assert get_udf('CASESENSITIVE')() == 'result'
        assert get_udf('cAsEsEnSiTiVe')() == 'result'

    def test_get_udf_not_found_raises_error(self):
        """Test that FunctionNotFoundError is raised when function not found."""

        @udf_tool(input_type=SimpleInput)
        def existing_func():
            pass
        with pytest.raises(FunctionNotFoundError) as exc_info:
            get_udf('nonexistent_func')
        error = exc_info.value
        assert error.context['function_name'] == 'nonexistent_func'
        assert 'existing_func' in error.context['available_functions']

    def test_get_udf_returns_callable(self):
        """Test that retrieved function is callable."""

        @udf_tool(input_type=SimpleInput)
        def callable_test(x):
            return x * 2
        func = get_udf('callable_test')
        assert callable(func)
        assert func(5) == 10


class TestListUDFs:
    """Tests for list_udfs() function."""

    def test_list_udfs_returns_all(self):
        """Test that list_udfs() returns all registered functions."""

        @udf_tool(input_type=SimpleInput)
        def func1():
            pass

        @udf_tool(input_type=SimpleInput)
        def func2():
            pass

        @udf_tool(input_type=SimpleInput)
        def func3():
            pass
        udfs = list_udfs()
        assert len(udfs) == 3
        names = [udf['name'] for udf in udfs]
        assert 'func1' in names
        assert 'func2' in names
        assert 'func3' in names

    def test_list_udfs_includes_metadata(self):
        """Test that list_udfs() includes all metadata fields."""

        @udf_tool(input_type=SimpleInput)
        def meta_test(a, b):
            """Test function."""
            pass
        udfs = list_udfs()
        assert len(udfs) == 1
        udf = udfs[0]
        assert udf['name'] == 'meta_test'
        assert 'test_udf_registry' in udf['module']
        assert 'file' in udf
        assert udf['docstring'] == 'Test function.'
        assert udf['signature'] == '(a, b)'

    def test_list_udfs_sorted_alphabetically(self):
        """Test that list_udfs() returns functions sorted alphabetically."""

        @udf_tool(input_type=SimpleInput)
        def zebra():
            pass

        @udf_tool(input_type=SimpleInput)
        def Alpha():
            pass

        @udf_tool(input_type=SimpleInput)
        def middle():
            pass
        udfs = list_udfs()
        names = [udf['name'] for udf in udfs]
        assert names == ['Alpha', 'middle', 'zebra']


class TestClearRegistry:
    """Tests for clear_registry() function."""

    def test_clear_registry(self):
        """Test that clear_registry() removes all functions."""

        @udf_tool(input_type=SimpleInput)
        def func1():
            pass

        @udf_tool(input_type=SimpleInput)
        def func2():
            pass
        assert len(UDF_REGISTRY) == 2
        clear_registry()
        assert len(UDF_REGISTRY) == 0
        assert list_udfs() == []

    def test_clear_registry_isolation(self):
        """Test that clear_registry() provides test isolation."""

        @udf_tool(input_type=SimpleInput)
        def test_func():
            pass
        clear_registry()
        with pytest.raises(FunctionNotFoundError):
            get_udf('test_func')


class TestExceptionContext:
    """Tests for exception context."""

    def test_duplicate_error_context(self):
        """Test that DuplicateFunctionError includes both locations."""

        @udf_tool(input_type=SimpleInput)
        def dup_func():
            pass
        try:

            @udf_tool(input_type=SimpleInput)
            def dup_func():  # noqa: F811
                pass
        except DuplicateFunctionError as e:
            assert e.context['function_name'] == 'dup_func'
            assert 'existing_location' in e.context
            assert 'new_location' in e.context
            assert 'test_udf_registry' in e.context['existing_location']
            assert 'test_udf_registry' in e.context['new_location']
            assert Path(e.context['existing_file']).exists()
            assert Path(e.context['new_file']).exists()

    def test_not_found_error_lists_available(self):
        """Test that FunctionNotFoundError lists available functions."""

        @udf_tool(input_type=SimpleInput)
        def available1():
            pass

        @udf_tool(input_type=SimpleInput)
        def available2():
            pass
        try:
            get_udf('missing_func')
        except FunctionNotFoundError as e:
            assert e.context['function_name'] == 'missing_func'
            assert 'available1' in e.context['available_functions']
            assert 'available2' in e.context['available_functions']
            assert len(e.context['available_functions']) == 2
