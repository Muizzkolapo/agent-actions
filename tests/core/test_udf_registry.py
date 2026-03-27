"""Tests for UDF registry and @udf_tool decorator."""

import pytest

from agent_actions.errors import FunctionNotFoundError
from agent_actions.utils.udf_management.registry import (
    UDF_REGISTRY,
    clear_registry,
    get_udf,
    udf_tool,
)


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clear registry before and after each test for isolation."""
    clear_registry()
    yield
    clear_registry()


class TestUDFRegistration:
    """Tests for @udf_tool decorator registration."""

    def test_registry_stores_metadata(self):
        """Test that all metadata is captured and stored."""

        @udf_tool()
        def metadata_func(x, y):
            """Function with metadata."""
            return x + y

        meta = UDF_REGISTRY["metadata_func"]
        assert meta["function"] == metadata_func
        assert meta["name"] == "metadata_func"
        assert "test_udf_registry" in meta["module"]
        assert meta["docstring"] == "Function with metadata."
        assert "file" in meta
        assert "signature" in meta
        assert str(meta["signature"]) == "(x, y)"

    def test_case_insensitive_duplicate_returns_existing(self):
        """Test that case-insensitive duplicates in same file return existing function."""

        @udf_tool()
        def My_Function():
            return "original"

        # Same file, different case - returns existing function
        @udf_tool()
        def my_function():  # noqa: F811
            return "duplicate"

        # Both keys map to same lowercase key, first one wins
        assert "my_function" in UDF_REGISTRY
        assert UDF_REGISTRY["my_function"]["function"]() == "original"


class TestUDFRetrieval:
    """Tests for get_udf() function."""

    def test_get_udf_retrieves_function(self):
        """Test that get_udf() retrieves registered function."""

        @udf_tool()
        def retrieve_test():
            return "retrieved"

        func = get_udf("retrieve_test")
        assert func() == "retrieved"

    def test_get_udf_not_found_raises_error(self):
        """Test that FunctionNotFoundError is raised when function not found."""

        @udf_tool()
        def existing_func():
            pass

        with pytest.raises(FunctionNotFoundError) as exc_info:
            get_udf("nonexistent_func")
        error = exc_info.value
        assert error.context["function_name"] == "nonexistent_func"
        assert "existing_func" in error.context["available_functions"]


class TestExceptionContext:
    """Tests for exception context."""

    def test_not_found_error_lists_available(self):
        """Test that FunctionNotFoundError lists available functions."""

        @udf_tool()
        def available1():
            pass

        @udf_tool()
        def available2():
            pass

        try:
            get_udf("missing_func")
        except FunctionNotFoundError as e:
            assert e.context["function_name"] == "missing_func"
            assert "available1" in e.context["available_functions"]
            assert "available2" in e.context["available_functions"]
            assert len(e.context["available_functions"]) == 2
