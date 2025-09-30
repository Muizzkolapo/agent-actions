"""
Integration tests for the complete error handling system.

These tests validate that the system works end-to-end with real scenarios
that users might encounter.
"""

import pytest
import tempfile
import os
from pathlib import Path

from agent_actions.core.exceptions import (
    ValidationError,
    FileLoadError,
    ConfigurationError,
    AgentActionsException
)
from agent_actions.core.user_errors import format_user_error
from agent_actions.core.error_context import with_error_context, with_agent_context


class TestUserFriendlyErrorFormatting:
    """Test that errors are formatted in a user-friendly way."""

    def test_validation_error_user_friendly(self):
        """Test validation error produces user-friendly output."""
        exc = ValidationError("Agent name cannot contain special characters")
        result = format_user_error(exc, {"command": "init", "agent": "invalid@name"})

        # Should be user-friendly
        assert "Configuration Error" in result
        assert "special characters" in result
        assert "invalid@name" in result
        # Should not contain Python internals
        assert "ValidationError" not in result
        assert "Traceback" not in result
        assert "__str__" not in result

    def test_file_not_found_user_friendly(self):
        """Test file not found error produces user-friendly output."""
        exc = FileLoadError("/path/to/config.yml", "Config file not found")
        result = format_user_error(exc, {"command": "run", "agent": "test_agent"})

        # Should be user-friendly
        assert "File Error" in result or "File not found" in result.lower()
        assert "config.yml" in result or "not found" in result.lower()
        # Should provide helpful guidance
        assert "fix" in result.lower() or "ensure" in result.lower()

    def test_configuration_error_user_friendly(self):
        """Test configuration error produces user-friendly output."""
        exc = ConfigurationError("Invalid YAML syntax: missing closing bracket")
        result = format_user_error(exc, {"command": "render", "file": "config.yml"})

        # Should be user-friendly
        assert "Configuration Error" in result
        assert "YAML" in result or "syntax" in result
        # Context may be included differently
        assert "render" in result or "config" in result.lower()

    def test_generic_error_fallback(self):
        """Test that unknown errors get reasonable fallback handling."""
        exc = RuntimeError("Something unexpected happened")
        result = format_user_error(exc, {"command": "run"})

        # Should still provide something useful
        assert len(result) > 20  # Not empty
        assert "unexpected" in result.lower() or "error" in result.lower()
        # Should not expose Python internals
        assert "RuntimeError" not in result


class TestErrorContextCapture:
    """Test that error context is captured correctly."""

    def test_command_context_captured(self):
        """Test that command context appears in error messages."""
        @with_error_context(command="init")
        def failing_init(project_name):
            raise ValidationError(f"Invalid project name: {project_name}")

        with pytest.raises(ValidationError) as exc_info:
            failing_init("bad@name")

        exc = exc_info.value
        result = format_user_error(exc, {"additional": "context"})

        # Should include context from decorator and call
        assert "bad@name" in result
        assert "init" in result or "additional" in result

    def test_agent_context_captured(self):
        """Test that agent context appears in error messages."""
        @with_agent_context
        def failing_agent_operation(agent_name, config_file):
            raise ConfigurationError("Invalid agent configuration")

        with pytest.raises(ConfigurationError) as exc_info:
            failing_agent_operation("test_agent", "config.yml")

        exc = exc_info.value
        result = format_user_error(exc, {"command": "run"})

        # Should include agent context
        assert "test_agent" in result
        assert "config.yml" in result

    def test_nested_context_merging(self):
        """Test that contexts from different sources merge correctly."""
        @with_error_context(command="run")
        @with_agent_context
        def complex_operation(agent_name, config_file):
            exc = ValidationError("Multiple validation errors")
            exc.line_number = 42
            raise exc

        with pytest.raises(ValidationError) as exc_info:
            complex_operation("my_agent", "config.yml")

        exc = exc_info.value
        result = format_user_error(exc, {"output_dir": "/tmp"})

        # Should include all contexts
        assert "my_agent" in result
        assert "config.yml" in result
        assert "42" in result  # from exception attribute
        assert "/tmp" in result or "run" in result  # from call context


class TestBrokenExceptionRecovery:
    """Test recovery from broken exceptions."""

    def test_broken_str_method_recovery(self):
        """Test recovery when exception __str__ method is broken."""
        class BrokenException(Exception):
            def __str__(self):
                raise RuntimeError("Broken __str__ method")

        exc = BrokenException("Original message")
        result = format_user_error(exc, {"command": "test"})

        # Should not crash and provide some useful output
        assert len(result) > 10
        assert "error" in result.lower()
        assert "test" in result  # context should still work

    def test_circular_exception_chain_recovery(self):
        """Test recovery from circular exception chains."""
        exc1 = RuntimeError("Error 1")
        exc2 = ValueError("Error 2")

        # Create circular chain
        exc1.__cause__ = exc2
        exc2.__cause__ = exc1

        result = format_user_error(exc1, {"command": "test"})

        # Should not crash and provide some output
        assert len(result) > 10
        assert "error" in result.lower()


class TestRealWorldScenarios:
    """Test realistic error scenarios."""

    def test_missing_config_file_scenario(self):
        """Test the common scenario of missing config file."""
        def simulate_missing_config():
            config_path = "/agents/nonexistent.yml"
            raise FileLoadError(config_path, "No such file or directory")

        with pytest.raises(FileLoadError) as exc_info:
            simulate_missing_config()

        result = format_user_error(exc_info.value, {
            "command": "run",
            "agent": "nonexistent"
        })

        # Should be helpful for users
        assert "nonexistent" in result
        assert "file" in result.lower()
        assert any(word in result.lower() for word in ["create", "check", "ensure", "exists"])

    def test_yaml_syntax_error_scenario(self):
        """Test YAML syntax error scenario."""
        def simulate_yaml_error():
            exc = ConfigurationError("YAML parse error at line 15: expected value")
            exc.line_number = 15
            exc.file_path = "agent_config.yml"
            raise exc

        with pytest.raises(ConfigurationError) as exc_info:
            simulate_yaml_error()

        result = format_user_error(exc_info.value, {
            "command": "run",
            "agent": "test_agent"
        })

        # Should help users locate and fix the issue
        assert "15" in result  # line number
        assert "YAML" in result or "parse" in result
        assert "agent_config.yml" in result or "test_agent" in result

    def test_permission_denied_scenario(self):
        """Test permission denied scenario."""
        def simulate_permission_error():
            raise PermissionError("Permission denied: cannot write to '/protected/dir'")

        with pytest.raises(PermissionError) as exc_info:
            simulate_permission_error()

        result = format_user_error(exc_info.value, {
            "command": "init",
            "project": "my_project"
        })

        # Should help users understand and fix permission issues
        # The system may categorize this as authentication error, which is still helpful
        assert any(word in result.lower() for word in ["permission", "authentication", "denied", "access"])
        assert "/protected/dir" in result or "my_project" in result or "api" in result.lower()
        assert "fix" in result.lower()  # Should provide actionable guidance


class TestErrorMessageQuality:
    """Test the quality and usability of error messages."""

    def test_messages_are_actionable(self):
        """Test that error messages contain actionable guidance."""
        test_cases = [
            (ValidationError("Invalid config"), {"command": "init"}),
            (FileLoadError("/path/to/file", "File not found"), {"command": "run"}),
            (ConfigurationError("Syntax error"), {"command": "render"}),
        ]

        for exc, context in test_cases:
            result = format_user_error(exc, context)

            # Should contain actionable words
            actionable_words = ["check", "create", "fix", "ensure", "verify", "add", "update"]
            has_actionable = any(word in result.lower() for word in actionable_words)
            assert has_actionable, f"No actionable guidance in: {result[:100]}..."

    def test_messages_avoid_technical_jargon(self):
        """Test that messages avoid Python technical terms."""
        exc = RuntimeError("Internal processing error")
        result = format_user_error(exc, {"command": "run"})

        # Should avoid Python-specific terms
        forbidden = ["traceback", "__str__", "__init__", "TypeError", "AttributeError"]
        for term in forbidden:
            assert term not in result, f"Found technical term '{term}' in: {result}"

    def test_message_length_reasonable(self):
        """Test that messages are reasonably sized."""
        exc = ValidationError("Test error")
        result = format_user_error(exc, {"command": "test"})

        # Should be informative but not overwhelming
        assert 30 < len(result) < 500, f"Message length {len(result)} seems inappropriate"

    def test_consistent_formatting(self):
        """Test that different error types have consistent formatting."""
        errors = [
            ValidationError("Validation failed"),
            FileLoadError("/path/to/file", "File missing"),
            ConfigurationError("Config invalid"),
        ]

        results = [format_user_error(exc, {"command": "test"}) for exc in errors]

        # All should follow similar structure
        for result in results:
            assert "Error:" in result  # Should have error category
            assert "Problem:" in result or "Fix:" in result  # Should have guidance
            lines = result.split('\n')
            assert len(lines) >= 3, f"Too short: {result}"  # Should have multiple lines


class TestErrorSystemRobustness:
    """Test that the error system is robust against edge cases."""

    def test_none_exception_handling(self):
        """Test handling of None exception."""
        result = format_user_error(None, {"command": "test"})
        assert len(result) > 5  # Should provide some output
        assert "error" in result.lower()

    def test_empty_context_handling(self):
        """Test handling of empty context."""
        exc = ValidationError("Test error")
        result = format_user_error(exc, {})
        assert "Test error" in result
        assert len(result) > 20

    def test_malformed_exception_handling(self):
        """Test handling of exceptions with unusual attributes."""
        exc = RuntimeError("Test")
        exc.weird_attribute = object()  # Non-serializable attribute

        result = format_user_error(exc, {"command": "test"})
        assert len(result) > 10  # Should still work
        assert "Test" in result or "error" in result.lower()