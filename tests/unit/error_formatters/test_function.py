"""Tests for FunctionNotFoundFormatter.

Locks in the narrowed contract introduced when UDFLoadError was moved out to
its own formatter: this one handles `FunctionNotFoundError` and
`DuplicateFunctionError` only, and must NOT claim `UDFLoadError` even if the
substring fallback would otherwise match.
"""

import pytest

from agent_actions.errors import (
    DuplicateFunctionError,
    FunctionNotFoundError,
    UDFLoadError,
)
from agent_actions.logging.errors.formatters.function import FunctionNotFoundFormatter


@pytest.fixture
def formatter():
    return FunctionNotFoundFormatter()


class TestCanHandle:
    def test_claims_function_not_found_error(self, formatter):
        exc = FunctionNotFoundError("Function 'foo' not found")
        assert formatter.can_handle(exc, exc, str(exc))

    def test_claims_duplicate_function_error(self, formatter):
        exc = DuplicateFunctionError(function_name="foo")
        assert formatter.can_handle(exc, exc, str(exc))

    def test_claims_when_function_not_found_is_root_cause(self, formatter):
        root = FunctionNotFoundError("Function 'foo' not found")
        wrapped = RuntimeError("workflow failed")
        wrapped.__cause__ = root
        assert formatter.can_handle(wrapped, root, str(root))

    def test_rejects_udf_load_error(self, formatter):
        """UDFLoadErrorFormatter owns UDFLoadError — function formatter must defer."""
        exc = UDFLoadError(module="proj.bad", file="/proj/bad.py", error="boom")
        assert not formatter.can_handle(exc, exc, str(exc))

    def test_rejects_udf_load_error_with_function_not_found_message(self, formatter):
        """Substring fallback must not steal UDFLoadError even when the error text
        contains 'function' + 'not found' (e.g. wrapped ImportError from a UDF that
        references a missing symbol)."""
        exc = UDFLoadError(
            module="proj.bad",
            file="/proj/bad.py",
            error="cannot import function 'foo' from module — not found",
        )
        assert not formatter.can_handle(exc, exc, str(exc))

    def test_rejects_udf_load_error_as_root_cause(self, formatter):
        """Defers even when UDFLoadError is wrapped — protects against chain reorders."""
        root = UDFLoadError(module="proj.bad", file="/proj/bad.py", error="boom")
        wrapped = RuntimeError("workflow failed")
        wrapped.__cause__ = root
        assert not formatter.can_handle(wrapped, root, str(root))

    def test_claims_untyped_error_with_function_not_found_message(self, formatter):
        """Substring fallback still catches generic errors that name a missing function."""
        exc = RuntimeError("function 'foo' not found in registry")
        assert formatter.can_handle(exc, exc, str(exc))

    def test_rejects_unrelated_error(self, formatter):
        exc = ValueError("something else entirely")
        assert not formatter.can_handle(exc, exc, str(exc))


class TestFormat:
    def test_renders_function_name_in_title(self, formatter):
        exc = FunctionNotFoundError("Function 'extract_facts' not found")
        result = formatter.format(exc, exc, str(exc), {"function_name": "extract_facts"})
        assert result.title == "Function 'extract_facts' not found"

    def test_renders_unknown_when_function_name_missing(self, formatter):
        exc = FunctionNotFoundError("Function not found")
        result = formatter.format(exc, exc, str(exc), {})
        assert result.title == "Function 'unknown' not found"

    def test_suggests_similar_function_when_available(self, formatter):
        # _find_similar_functions matches via substring containment, so the
        # target must be a sub/super-string of an available function.
        exc = FunctionNotFoundError("Function 'extract' not found")
        result = formatter.format(
            exc,
            exc,
            str(exc),
            {
                "function_name": "extract",
                "available_functions": ["extract_facts", "extract_links", "summarize"],
            },
        )
        assert "Did you mean" in result.fix
        assert "extract_facts" in result.fix

    def test_lists_list_udfs_command_when_available_functions_known(self, formatter):
        exc = FunctionNotFoundError("Function 'foo' not found")
        result = formatter.format(
            exc,
            exc,
            str(exc),
            {"function_name": "foo", "available_functions": ["a", "b", "c"]},
        )
        assert "agac list-udfs" in result.fix
        assert "3 available functions" in result.fix

    def test_generic_fix_when_no_similar_and_no_available(self, formatter):
        exc = FunctionNotFoundError("Function 'foo' not found")
        result = formatter.format(exc, exc, str(exc), {"function_name": "foo"})
        assert "@udf_tool decorator" in result.fix
        assert "user_code directory" in result.fix
