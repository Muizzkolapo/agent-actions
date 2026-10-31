"""
Tests for exceptions module — __str__ (concise) and detailed_str() (with context).
"""

from agent_actions.errors import AgentActionsError
from agent_actions.errors.base import get_error_detail


class TestAgentActionsError:
    """Test AgentActionsError string output."""

    def test_str_returns_message_only(self):
        """str() returns just the message, not the context."""
        context = {"agent": "test_agent", "file": "config.yml", "line": 10}
        exc = AgentActionsError("Test error message", context)
        result = str(exc)
        assert result == "Test error message"
        assert "agent=test_agent" not in result

    def test_str_without_context(self):
        """str() without context still works."""
        exc = AgentActionsError("Test error message")
        result = str(exc)
        assert result == "Test error message"
        assert "Context:" not in result

    def test_detailed_str_with_dict_context(self):
        """detailed_str() includes context from dict."""
        context = {"agent": "test_agent", "file": "config.yml", "line": 10}
        exc = AgentActionsError("Test error message", context)
        result = exc.detailed_str()
        assert "Test error message" in result
        assert "agent=test_agent" in result
        assert "file=config.yml" in result
        assert "line=10" in result

    def test_detailed_str_with_string_context(self):
        """detailed_str() handles string context."""
        context = "simple string context"
        exc = AgentActionsError("Test error message", context)
        result = exc.detailed_str()
        assert "Test error message" in result
        assert "simple string context" in result

    def test_detailed_str_with_broken_context_object(self):
        """detailed_str() handles context with broken __str__."""

        class BrokenObject:
            def __str__(self):
                raise RuntimeError("Broken __str__ method")

            def __repr__(self):
                return "BrokenObject()"

        context = BrokenObject()
        exc = AgentActionsError("Test error message", context)
        result = exc.detailed_str()
        assert "Test error message" in result
        assert "BrokenObject" in result or "Error formatting context" in result

    def test_detailed_str_without_context(self):
        """detailed_str() without context returns just the message."""
        exc = AgentActionsError("Test error message")
        result = exc.detailed_str()
        assert result == "Test error message"


class TestGetErrorDetail:
    """Test get_error_detail() helper."""

    def test_returns_detailed_str_for_agent_actions_error(self):
        """get_error_detail() calls detailed_str() for AgentActionsError."""
        context = {"key": "value"}
        exc = AgentActionsError("Something failed", context)
        result = get_error_detail(exc)
        assert "key=value" in result
        assert "Something failed" in result

    def test_returns_str_for_plain_exception(self):
        """get_error_detail() falls back to str() for non-AgentActionsError."""
        exc = ValueError("plain error")
        result = get_error_detail(exc)
        assert result == "plain error"
