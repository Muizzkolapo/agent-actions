"""
Tests for exceptions module - specifically the fixed __str__ method.
"""

import pytest
from agent_actions.core.exceptions import AgentActionsException


class TestAgentActionsException:
    """Test AgentActionsException class, especially the fixed __str__ method."""

    def test_exception_with_dict_context(self):
        """Test exception with dictionary context."""
        context = {"agent": "test_agent", "file": "config.yml", "line": 10}
        exc = AgentActionsException("Test error message", context)

        # Should not raise exception when converting to string
        result = str(exc)

        assert "Test error message" in result
        assert "agent=test_agent" in result
        assert "file=config.yml" in result
        assert "line=10" in result

    def test_exception_with_string_context(self):
        """Test exception with string context (the bug case)."""
        context = "simple string context"
        exc = AgentActionsException("Test error message", context)

        # This was the original failing case - should not crash
        result = str(exc)

        assert "Test error message" in result
        assert "simple string context" in result

    def test_exception_with_none_context(self):
        """Test exception with None context."""
        exc = AgentActionsException("Test error message", None)

        result = str(exc)
        assert "Test error message" in result
        # Should not include context section
        assert "Context:" not in result

    def test_exception_with_empty_dict_context(self):
        """Test exception with empty dictionary context."""
        exc = AgentActionsException("Test error message", {})

        result = str(exc)
        assert "Test error message" in result
        # Should not include context section for empty dict
        assert "Context:" not in result

    def test_exception_with_list_context(self):
        """Test exception with list context."""
        context = ["item1", "item2", "item3"]
        exc = AgentActionsException("Test error message", context)

        result = str(exc)
        assert "Test error message" in result
        assert "item1" in result
        assert "item2" in result
        assert "item3" in result

    def test_exception_with_complex_object_context(self):
        """Test exception with complex object context."""
        class CustomObject:
            def __init__(self):
                self.name = "test_object"
                self.value = 42

            def __str__(self):
                return f"CustomObject(name={self.name}, value={self.value})"

        context = CustomObject()
        exc = AgentActionsException("Test error message", context)

        result = str(exc)
        assert "Test error message" in result
        assert "CustomObject" in result

    def test_exception_with_broken_context_object(self):
        """Test exception with context object that has broken __str__."""
        class BrokenObject:
            def __str__(self):
                raise RuntimeError("Broken __str__ method")

            def __repr__(self):
                return "BrokenObject()"

        context = BrokenObject()
        exc = AgentActionsException("Test error message", context)

        # Should not crash - should use safe fallback
        result = str(exc)
        assert "Test error message" in result
        # Should contain some representation of the object
        assert "BrokenObject" in result or "Error formatting context" in result

    def test_exception_with_nested_dict_context(self):
        """Test exception with nested dictionary context."""
        context = {
            "agent": "test_agent",
            "config": {
                "file": "test.yml",
                "section": "agents",
                "settings": {
                    "timeout": 30,
                    "retries": 3
                }
            },
            "step": "validation"
        }
        exc = AgentActionsException("Test error message", context)

        result = str(exc)
        assert "Test error message" in result
        assert "agent=test_agent" in result
        assert "config=" in result
        assert "file" in result and "test.yml" in result
        assert "section" in result and "agents" in result
        assert "settings" in result
        assert "timeout" in result and "30" in result
        assert "step=validation" in result

    def test_exception_without_context(self):
        """Test exception without context parameter."""
        exc = AgentActionsException("Test error message")

        result = str(exc)
        assert result == "Test error message"
        assert "Context:" not in result

    def test_exception_inheritance(self):
        """Test that AgentActionsException is properly inheritable."""
        class CustomException(AgentActionsException):
            pass

        exc = CustomException("Custom error", {"key": "value"})
        result = str(exc)

        assert "Custom error" in result
        assert "key=value" in result

    def test_exception_with_numeric_context(self):
        """Test exception with numeric context values."""
        context = {
            "line_number": 42,
            "error_count": 3,
            "timeout": 30.5,
            "success_rate": 0.95
        }
        exc = AgentActionsException("Numeric context test", context)

        result = str(exc)
        assert "line_number=42" in result
        assert "error_count=3" in result
        assert "timeout=30.5" in result
        assert "success_rate=0.95" in result

    def test_exception_context_with_special_characters(self):
        """Test exception context with special characters."""
        context = {
            "file_path": "/path/with spaces/config.yml",
            "message": "Error: invalid 'syntax' in \"config\"",
            "pattern": "*.yml",
            "unicode": "测试"
        }
        exc = AgentActionsException("Special characters test", context)

        result = str(exc)
        assert "/path/with spaces/config.yml" in result
        assert "Error: invalid 'syntax' in \"config\"" in result
        assert "*.yml" in result
        assert "测试" in result

    def test_multiple_exceptions_with_different_contexts(self):
        """Test creating multiple exceptions doesn't interfere with each other."""
        exc1 = AgentActionsException("First error", {"type": "error1"})
        exc2 = AgentActionsException("Second error", "string context")
        exc3 = AgentActionsException("Third error", {"type": "error3"})

        result1 = str(exc1)
        result2 = str(exc2)
        result3 = str(exc3)

        assert "First error" in result1 and "type=error1" in result1
        assert "Second error" in result2 and "string context" in result2
        assert "Third error" in result3 and "type=error3" in result3

        # Ensure no cross-contamination
        assert "error1" not in result2
        assert "error3" not in result2
        assert "string context" not in result1
        assert "string context" not in result3

    def test_exception_repr_method(self):
        """Test exception __repr__ method."""
        exc = AgentActionsException("Test message", {"key": "value"})
        repr_result = repr(exc)

        # Should contain class name and message
        assert "AgentActionsException" in repr_result
        assert "Test message" in repr_result

    def test_exception_args_preserved(self):
        """Test that exception args are preserved."""
        exc = AgentActionsException("Test message", {"key": "value"})

        assert exc.args == ("Test message",)
        assert exc.context == {"key": "value"}

    def test_exception_with_empty_string_context(self):
        """Test exception with empty string context."""
        exc = AgentActionsException("Test error", "")

        result = str(exc)
        assert "Test error" in result
        # Empty string context should not add context section
        assert "Context:" not in result