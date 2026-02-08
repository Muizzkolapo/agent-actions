"""
Tests for exceptions module - specifically the fixed __str__ method.
"""

from agent_actions.errors import AgentActionsException


class TestAgentActionsException:
    """Test AgentActionsException class, especially the fixed __str__ method."""

    def test_exception_with_dict_context(self):
        """Test exception with dictionary context."""
        context = {"agent": "test_agent", "file": "config.yml", "line": 10}
        exc = AgentActionsException("Test error message", context)
        result = str(exc)
        assert "Test error message" in result
        assert "agent=test_agent" in result
        assert "file=config.yml" in result
        assert "line=10" in result

    def test_exception_with_string_context(self):
        """Test exception with string context (the bug case)."""
        context = "simple string context"
        exc = AgentActionsException("Test error message", context)
        result = str(exc)
        assert "Test error message" in result
        assert "simple string context" in result

    def test_exception_with_broken_context_object(self):
        """Test exception with context object that has broken __str__."""

        class BrokenObject:
            def __str__(self):
                raise RuntimeError("Broken __str__ method")

            def __repr__(self):
                return "BrokenObject()"

        context = BrokenObject()
        exc = AgentActionsException("Test error message", context)
        result = str(exc)
        assert "Test error message" in result
        assert "BrokenObject" in result or "Error formatting context" in result

    def test_exception_without_context(self):
        """Test exception without context parameter."""
        exc = AgentActionsException("Test error message")
        result = str(exc)
        assert result == "Test error message"
        assert "Context:" not in result
