"""
Tests for safe_format module error handling utilities.
"""

from unittest.mock import Mock

from agent_actions.utils.safe_format import (
    extract_root_cause,
    format_exception_context,
    get_error_chain,
    safe_format_error,
)


class BrokenStrException(Exception):
    """Exception with broken __str__ method for testing."""

    def __str__(self):
        raise RuntimeError("Broken __str__ method")


class CircularException(Exception):
    """Exception that creates circular reference in __str__."""

    def __init__(self, message, circular_ref=None):
        super().__init__(message)
        self.circular_ref = circular_ref or self

    def __str__(self):
        # This will cause infinite recursion
        return f"{super().__str__()} - {self.circular_ref}"


class TestSafeFormatError:
    """Test safe_format_error function."""

    def test_normal_exception(self):
        """Test formatting normal exception."""
        exc = ValueError("Test error message")
        result = safe_format_error(exc)
        assert "Test error message" in result

    def test_broken_str_exception(self):
        """Test formatting exception with broken __str__ method."""
        exc = BrokenStrException("This won't be seen")
        result = safe_format_error(exc)
        assert "BrokenStrException" in result
        assert "unable to format message" in result or "BrokenStrException" in result

    def test_circular_reference_exception(self):
        """Test formatting exception with circular reference."""
        exc = CircularException("Test message")
        result = safe_format_error(exc)
        assert "CircularException" in result
        assert "unable to format message" in result or "CircularException" in result

    def test_non_exception_object(self):
        """Test formatting non-exception object."""
        result = safe_format_error("not an exception")
        assert result == "not an exception"

    def test_exception_with_context(self):
        """Test formatting exception with context attribute."""
        exc = ValueError("Test error")
        exc.context = {"agent": "test_agent", "file": "config.yml"}
        result = safe_format_error(exc)
        assert "Test error" in result
        # Note: safe_format_error doesn't include context - that's handled elsewhere


class TestExtractRootCause:
    """Test extract_root_cause function."""

    def test_chained_exceptions(self):
        """Test extracting root cause from chained exceptions."""
        root = ValueError("Root error")
        middle = RuntimeError("Middle error")
        top = TypeError("Top error")

        middle.__cause__ = root
        top.__cause__ = middle

        result = extract_root_cause(top)
        assert result == root

    def test_suppressed_exceptions(self):
        """Test extracting root cause with suppressed exceptions."""
        root = ValueError("Root error")
        exc = RuntimeError("Main error")
        exc.__suppress_context__ = False
        exc.__context__ = root

        result = extract_root_cause(exc)
        assert result == root

    def test_circular_exception_chain(self):
        """Test handling circular exception chains."""
        exc1 = ValueError("Error 1")
        exc2 = RuntimeError("Error 2")

        # Create circular reference
        exc1.__cause__ = exc2
        exc2.__cause__ = exc1

        result = extract_root_cause(exc1)
        # Should return the starting exception when circular
        assert result == exc1

    def test_broken_exception_in_chain(self):
        """Test handling broken exception in chain."""
        root = BrokenStrException("Root error")
        top = ValueError("Top error")
        top.__cause__ = root

        result = extract_root_cause(top)
        assert result == root


class TestGetErrorChain:
    """Test get_error_chain function."""

    def test_multiple_exception_chain(self):
        """Test getting chain from multiple exceptions."""
        root = ValueError("Root error")
        middle = RuntimeError("Middle error")
        top = TypeError("Top error")

        middle.__cause__ = root
        top.__cause__ = middle

        chain = get_error_chain(top)
        assert len(chain) == 3
        assert chain[0] == top
        assert chain[1] == middle
        assert chain[2] == root

    def test_circular_chain_prevention(self):
        """Test prevention of infinite loops in circular chains."""
        exc1 = ValueError("Error 1")
        exc2 = RuntimeError("Error 2")

        exc1.__cause__ = exc2
        exc2.__cause__ = exc1

        chain = get_error_chain(exc1)
        # Should detect cycle and stop
        assert len(chain) == 2
        assert exc1 in chain
        assert exc2 in chain


class TestFormatExceptionContext:
    """Test format_exception_context function."""

    def test_dict_context(self):
        """Test formatting dictionary context."""
        context = {"agent": "test_agent", "config": "test.yml"}
        result = format_exception_context(context)
        assert "agent=test_agent" in result
        assert "config=test.yml" in result

    def test_string_context(self):
        """Test formatting string context."""
        context = "Simple string context"
        result = format_exception_context(context)
        assert result == "Simple string context"

    def test_list_context(self):
        """Test formatting list context."""
        context = ["item1", "item2", "item3"]
        result = format_exception_context(context)
        assert "item1" in result
        assert "item2" in result
        assert "item3" in result

    def test_complex_object_context(self):
        """Test formatting complex object context."""
        context = Mock()
        context.name = "test"
        result = format_exception_context(context)
        # Should fall back to string representation
        assert "Mock" in result or "test" in result

    def test_broken_context_formatting(self):
        """Test handling context that breaks during formatting."""

        class BrokenContext:
            def __str__(self):
                raise ValueError("Broken context")

            def __repr__(self):
                raise ValueError("Broken repr too")

        context = BrokenContext()
        result = format_exception_context(context)
        # Should provide safe fallback
        assert "BrokenContext" in result and "unable to format" in result

    def test_nested_dict_context(self):
        """Test formatting nested dictionary context."""
        context = {"agent": "test_agent", "config": {"file": "test.yml", "section": "agents"}}
        result = format_exception_context(context)
        assert "agent=test_agent" in result
        assert "config=" in result
        # Nested dict gets formatted as string representation
