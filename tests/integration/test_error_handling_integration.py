"""
Integration tests for complete error handling system.

These tests validate the end-to-end error handling flow from
exception occurrence through user-friendly formatting.
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, Mock

from agent_actions.core.exceptions import (
    ValidationError,
    FileNotFoundError,
    ConfigurationError,
    AgentActionsException
)
from agent_actions.core.user_errors import format_user_error
from agent_actions.core.error_context import with_command_context, with_agent_context


class TestEndToEndErrorHandling:
    """Test complete error handling flow."""

    def test_validation_error_end_to_end(self):
        """Test validation error from occurrence to user message."""
        @with_command_context("init")
        def create_project(project_name, template="default"):
            if "@" in project_name:
                raise ValidationError(f"Project name '{project_name}' contains invalid characters")

        # Simulate error occurrence
        with pytest.raises(ValidationError) as exc_info:
            create_project("invalid@project", template="minimal")

        # Format for user
        exc = exc_info.value
        user_message = format_user_error(exc, {"command": "init"})

        # Verify user-friendly output
        assert "Configuration Error" in user_message
        assert "invalid@project" in user_message
        assert "invalid characters" in user_message
        assert "template: minimal" in user_message
        assert "command: init" in user_message
        # Should not contain Python internals
        assert "ValidationError" not in user_message
        assert "Traceback" not in user_message

    def test_file_not_found_end_to_end(self):
        """Test file not found error from occurrence to user message."""
        @with_agent_context
        def load_agent_config(agent_name, config_dir="/configs"):
            config_path = f"{config_dir}/{agent_name}.yml"
            if not os.path.exists(config_path):
                raise FileNotFoundError(f"Agent configuration file not found: {config_path}")

        # Simulate error occurrence
        with pytest.raises(FileNotFoundError) as exc_info:
            load_agent_config("missing_agent", config_dir="/tmp/nonexistent")

        # Format for user
        exc = exc_info.value
        user_message = format_user_error(exc, {"command": "run"})

        # Verify user-friendly output
        assert "File Not Found" in user_message
        assert "missing_agent.yml" in user_message
        assert "/tmp/nonexistent" in user_message
        assert "agent_name: missing_agent" in user_message
        assert "command: run" in user_message
        # Should provide helpful guidance
        assert "create" in user_message.lower() or "check" in user_message.lower()

    def test_configuration_error_end_to_end(self):
        """Test configuration error from occurrence to user message."""
        @with_command_context("render")
        @with_agent_context
        def parse_yaml_config(agent_name, config_content):
            if "invalid_yaml: [" in config_content:
                exc = ConfigurationError("Invalid YAML syntax: unclosed bracket")
                exc.line_number = 5
                exc.config_file = f"{agent_name}.yml"
                raise exc

        # Simulate error occurrence
        with pytest.raises(ConfigurationError) as exc_info:
            parse_yaml_config("test_agent", "invalid_yaml: [missing_close")

        # Format for user
        exc = exc_info.value
        user_message = format_user_error(exc, {"command": "render"})

        # Verify user-friendly output
        assert "Configuration Error" in user_message
        assert "YAML syntax" in user_message
        assert "test_agent.yml" in user_message
        assert "line_number: 5" in user_message
        assert "agent_name: test_agent" in user_message
        assert "command: render" in user_message

    def test_nested_exception_handling(self):
        """Test handling of nested exception chains."""
        @with_command_context("run")
        def outer_function(agent_name):
            try:
                inner_function(agent_name)
            except Exception as e:
                raise RuntimeError(f"Failed to process agent '{agent_name}'") from e

        def inner_function(agent_name):
            if agent_name == "broken_agent":
                raise ValidationError("Agent configuration is invalid")

        # Simulate error occurrence
        with pytest.raises(RuntimeError) as exc_info:
            outer_function("broken_agent")

        # Format for user - should focus on root cause
        exc = exc_info.value
        user_message = format_user_error(exc, {"command": "run"})

        # Should prioritize the validation error (root cause)
        assert "Configuration Error" in user_message or "configuration is invalid" in user_message
        assert "broken_agent" in user_message

    def test_broken_exception_recovery(self):
        """Test recovery from broken exception __str__ methods."""
        class BrokenAgentException(AgentActionsException):
            def __str__(self):
                raise RuntimeError("Broken __str__ method")

        @with_command_context("test")
        def failing_operation():
            exc = BrokenAgentException("Original message", {"agent": "test_agent"})
            raise exc

        # Simulate error occurrence
        with pytest.raises(BrokenAgentException) as exc_info:
            failing_operation()

        # Format for user - should handle gracefully
        exc = exc_info.value
        user_message = format_user_error(exc, {"command": "test"})

        # Should provide some useful output despite broken __str__
        assert len(user_message) > 0
        assert "Error" in user_message
        assert "test_agent" in user_message
        assert "command: test" in user_message

    def test_context_merging_across_decorators(self):
        """Test context merging from multiple decorators."""
        @with_command_context("run")
        @with_agent_context
        def complex_operation(agent_name, config_file, output_dir):
            exc = ValidationError("Multiple validation errors found")
            exc.error_count = 3
            raise exc

        # Simulate error occurrence
        with pytest.raises(ValidationError) as exc_info:
            complex_operation("test_agent", "config.yml", "/output")

        # Format for user
        exc = exc_info.value
        user_message = format_user_error(exc, {"additional": "context"})

        # Should include context from all sources
        assert "agent_name: test_agent" in user_message
        assert "config_file: config.yml" in user_message
        assert "output_dir: /output" in user_message
        assert "command: run" in user_message
        assert "additional: context" in user_message
        assert "error_count: 3" in user_message


class TestRealWorldScenarios:
    """Test realistic error scenarios that might occur in production."""

    def test_missing_agent_config_scenario(self):
        """Test scenario: User tries to run non-existent agent."""
        def simulate_agent_run(agent_name):
            config_path = f"/agents/{agent_name}.yml"
            raise FileNotFoundError(f"No such file or directory: '{config_path}'")

        with pytest.raises(FileNotFoundError) as exc_info:
            simulate_agent_run("nonexistent_agent")

        user_message = format_user_error(exc_info.value, {
            "command": "run",
            "agent": "nonexistent_agent"
        })

        # Should be helpful for users
        assert "File Not Found" in user_message
        assert "nonexistent_agent.yml" in user_message
        assert "create" in user_message.lower() or "check" in user_message.lower()

    def test_yaml_syntax_error_scenario(self):
        """Test scenario: User has syntax error in YAML config."""
        def simulate_yaml_parsing(config_content):
            exc = ConfigurationError("YAML syntax error at line 15: expected a value")
            exc.line_number = 15
            exc.column = 8
            raise exc

        with pytest.raises(ConfigurationError) as exc_info:
            simulate_yaml_parsing("invalid: yaml: content")

        user_message = format_user_error(exc_info.value, {
            "command": "run",
            "file": "agent_config.yml"
        })

        assert "Configuration Error" in user_message
        assert "line 15" in user_message
        assert "YAML syntax" in user_message
        assert "agent_config.yml" in user_message

    def test_permission_denied_scenario(self):
        """Test scenario: User lacks permissions for operation."""
        def simulate_permission_error():
            raise PermissionError("Permission denied: cannot write to '/protected/output'")

        with pytest.raises(PermissionError) as exc_info:
            simulate_permission_error()

        user_message = format_user_error(exc_info.value, {
            "command": "init",
            "output_dir": "/protected/output"
        })

        assert "Permission Denied" in user_message
        assert "/protected/output" in user_message
        assert "permissions" in user_message.lower()

    def test_template_rendering_error_scenario(self):
        """Test scenario: Template rendering fails."""
        def simulate_template_error():
            exc = ConfigurationError("Template variable 'undefined_var' is not defined")
            exc.template_file = "workflow.j2"
            exc.line_number = 23
            raise exc

        with pytest.raises(ConfigurationError) as exc_info:
            simulate_template_error()

        user_message = format_user_error(exc_info.value, {
            "command": "render",
            "agent": "test_agent",
            "template_dir": "./templates"
        })

        assert "Configuration Error" in user_message
        assert "undefined_var" in user_message
        assert "workflow.j2" in user_message
        assert "line 23" in user_message

    def test_agent_execution_timeout_scenario(self):
        """Test scenario: Agent execution times out."""
        def simulate_timeout_error():
            exc = RuntimeError("Agent execution timed out after 300 seconds")
            exc.timeout_seconds = 300
            exc.agent_status = "running"
            raise exc

        with pytest.raises(RuntimeError) as exc_info:
            simulate_timeout_error()

        user_message = format_user_error(exc_info.value, {
            "command": "run",
            "agent": "slow_agent"
        })

        assert "timed out" in user_message.lower()
        assert "300 seconds" in user_message
        assert "slow_agent" in user_message


class TestErrorMessageQuality:
    """Test quality and helpfulness of error messages."""

    def test_error_messages_are_actionable(self):
        """Test that error messages provide actionable guidance."""
        test_cases = [
            (ValidationError("Invalid agent name"), {"command": "init"}),
            (FileNotFoundError("Config file not found"), {"command": "run"}),
            (ConfigurationError("YAML syntax error"), {"command": "render"}),
            (PermissionError("Access denied"), {"command": "init"}),
        ]

        for exc, context in test_cases:
            user_message = format_user_error(exc, context)

            # Should contain actionable words
            actionable_words = ["check", "create", "fix", "ensure", "verify", "add", "remove", "modify"]
            has_actionable_guidance = any(word in user_message.lower() for word in actionable_words)
            assert has_actionable_guidance, f"Message lacks actionable guidance: {user_message}"

    def test_error_messages_avoid_technical_jargon(self):
        """Test that error messages avoid Python-specific terminology."""
        exc = RuntimeError("Some internal error")
        user_message = format_user_error(exc, {"command": "run"})

        # Should not contain Python internals
        forbidden_terms = [
            "Traceback", "stacktrace", "__str__", "__init__", "TypeError",
            "AttributeError", "KeyError", "IndexError", "module", "class"
        ]

        for term in forbidden_terms:
            assert term not in user_message, f"Message contains technical term '{term}': {user_message}"

    def test_error_messages_include_context(self):
        """Test that error messages include relevant context."""
        exc = ValidationError("Invalid configuration")
        context = {
            "command": "run",
            "agent": "test_agent",
            "config_file": "config.yml",
            "line_number": 42
        }

        user_message = format_user_error(exc, context)

        # Should include all relevant context
        assert "test_agent" in user_message
        assert "config.yml" in user_message
        assert "42" in user_message
        assert "run" in user_message

    def test_error_message_length_appropriate(self):
        """Test that error messages are appropriately sized."""
        exc = ValidationError("Test error")
        user_message = format_user_error(exc, {"command": "test"})

        # Should be informative but not overwhelming
        assert 50 < len(user_message) < 1000, f"Message length inappropriate: {len(user_message)} chars"

        # Should not be just the error repeated
        assert "Test error" in user_message
        assert len(user_message) > len("Test error") + 20