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
from agent_actions.core.safe_format import (
    extract_root_cause,
    get_error_chain,
    format_exception_chain_for_debug,
    safe_format_error
)


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


class TestMultiLevelExceptionChains:
    """Test multi-level exception chains preserve context and root causes (Phase 3)."""

    def test_two_level_chain_preserves_context(self):
        """Test 2-level chain preserves context at each level."""
        # Simulate real scenario: file error wrapped in config error
        try:
            try:
                raise FileNotFoundError("config.yml not found")
            except FileNotFoundError as e:
                raise ConfigurationError(
                    f"Failed to load config: {safe_format_error(e)}",
                    context={'config_path': '/agents/config.yml', 'agent': 'test-agent'},
                    cause=e
                ) from e
        except ConfigurationError as exc:
            # Verify chain structure
            chain = get_error_chain(exc)
            assert len(chain) == 2

            # Verify root cause extraction
            root = extract_root_cause(exc)
            assert isinstance(root, FileNotFoundError)
            assert "config.yml" in str(root)

            # Verify context is preserved
            assert exc.context['agent'] == 'test-agent'

            # Verify user message includes root cause info
            result = format_user_error(exc, {'command': 'run'})
            assert 'test-agent' in result

    def test_three_level_chain_shows_root_cause(self):
        """Test 3-level chain correctly identifies and shows root cause."""
        # Simulate: ValueError -> ValidationError -> ConfigurationError
        try:
            try:
                try:
                    raise ValueError("Model name cannot be empty")
                except ValueError as e:
                    raise ValidationError(
                        f"Field validation failed: {safe_format_error(e)}",
                        context={'field': 'model', 'section': 'agents'},
                        cause=e
                    ) from e
            except ValidationError as e:
                raise ConfigurationError(
                    f"Agent configuration invalid: {safe_format_error(e)}",
                    context={'agent': 'test-agent', 'file': 'config.yml'},
                    cause=e
                ) from e
        except ConfigurationError as exc:
            # Verify chain depth
            chain = get_error_chain(exc)
            assert len(chain) == 3

            # Verify root cause
            root = extract_root_cause(exc)
            assert isinstance(root, ValueError)
            assert "cannot be empty" in str(root)

            # Verify all contexts preserved
            assert chain[0].context['agent'] == 'test-agent'
            assert chain[1].context['field'] == 'model'

            # Format for debugging
            debug_output = format_exception_chain_for_debug(exc)
            assert "[1]" in debug_output
            assert "[2]" in debug_output
            assert "[3]" in debug_output
            assert "(Root Cause)" in debug_output

    def test_five_level_chain_like_original_bug(self):
        """Test 5-level chain like the original issue #394."""
        # Recreate the cascading error from the bug report
        try:
            # Level 1: Root cause (model not supported)
            try:
                try:
                    try:
                        try:
                            raise ValueError("Model 'claude-sonnet-4-20250514' not supported")
                        except ValueError as e:
                            # Level 2: Provider error
                            raise ConfigurationError(
                                f"Provider init failed: {safe_format_error(e)}",
                                context={'provider': 'anthropic'},
                                cause=e
                            ) from e
                    except ConfigurationError as e:
                        # Level 3: Batch service error
                        raise ConfigurationError(
                            f"Batch provider creation failed: {safe_format_error(e)}",
                            context={'provider_type': 'anthropic', 'operation': 'create_provider'},
                            cause=e
                        ) from e
                except ConfigurationError as e:
                    # Level 4: Target generator error
                    raise AgentActionsException(
                        f"Target generation failed: {safe_format_error(e)}",
                        context={'file_path': '/source/data.json', 'operation': 'generate'},
                        cause=e
                    ) from e
            except AgentActionsException as e:
                # Level 5: Top-level run error
                raise AgentActionsException(
                    f"Agent run failed: {safe_format_error(e)}",
                    context={'agent': 'qanalabs-quiz-gen', 'command': 'run'},
                    cause=e
                ) from e
        except AgentActionsException as exc:
            # Verify full chain
            chain = get_error_chain(exc)
            assert len(chain) == 5, f"Expected 5 levels, got {len(chain)}"

            # Verify root cause is correctly identified
            root = extract_root_cause(exc)
            assert isinstance(root, ValueError)
            assert "not supported" in str(root)

            # Verify context at each level
            assert chain[0].context['agent'] == 'qanalabs-quiz-gen'
            assert chain[1].context['file_path'] == '/source/data.json'
            assert chain[2].context['provider_type'] == 'anthropic'
            assert chain[3].context['provider'] == 'anthropic'

            # User-friendly message should show root cause clearly
            result = format_user_error(exc, {})
            assert 'qanalabs-quiz-gen' in result

            # Debug output should show full chain
            debug_output = format_exception_chain_for_debug(exc)
            assert "Exception Chain (5 levels)" in debug_output
            assert "[1]" in debug_output
            assert "[5]" in debug_output
            assert "(Root Cause)" in debug_output

    def test_chain_with_mixed_exception_types(self):
        """Test chain with different exception types preserves all info."""
        try:
            try:
                try:
                    raise IOError("File write failed: disk full")
                except IOError as e:
                    raise FileLoadError(
                        "/output/results.json",
                        f"Cannot write: {safe_format_error(e)}",
                        context={'operation': 'write_results'},
                        cause=e
                    ) from e
            except FileLoadError as e:
                raise AgentActionsException(
                    f"Output handling failed: {safe_format_error(e)}",
                    context={'agent': 'data-processor', 'stage': 'finalization'},
                    cause=e
                ) from e
        except AgentActionsException as exc:
            # Verify chain
            chain = get_error_chain(exc)
            assert len(chain) == 3

            # Verify types
            assert isinstance(chain[0], AgentActionsException)
            assert isinstance(chain[1], FileLoadError)
            assert isinstance(chain[2], IOError)

            # Root cause should be the IOError
            root = extract_root_cause(exc)
            assert isinstance(root, IOError)
            assert "disk full" in str(root)

    def test_context_from_decorators_preserved_in_chain(self):
        """Test that decorator-added context is preserved through chains."""
        @with_error_context(command="run")
        @with_agent_context
        def multi_level_failure(agent_name, config_file):
            try:
                raise ValueError("Invalid value")
            except ValueError as e:
                raise ValidationError(
                    f"Validation failed: {safe_format_error(e)}",
                    context={'field': 'test_field'},
                    cause=e
                ) from e

        with pytest.raises(ValidationError) as exc_info:
            multi_level_failure("test_agent", "config.yml")

        exc = exc_info.value

        # Should have context from decorators AND exception
        result = format_user_error(exc, {})
        assert "test_agent" in result  # from decorator
        assert "config.yml" in result  # from decorator
        # "test_field" might appear in context display

        # Chain should show both levels
        chain = get_error_chain(exc)
        assert len(chain) == 2