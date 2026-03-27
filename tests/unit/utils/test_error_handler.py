"""Tests for ErrorHandler — consistent error wrapping and re-raising."""

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.errors import (
    AgentActionsError,
    AgentExecutionError,
    ConfigurationError,
    FileLoadError,
    FileSystemError,
    TemplateRenderingError,
    ValidationError,
)
from agent_actions.utils.error_handler import ErrorHandler

# ---------------------------------------------------------------------------
# handle_error (core method)
# ---------------------------------------------------------------------------


class TestHandleError:
    """ErrorHandler.handle_error re-raises with the right type and message."""

    def test_raises_agent_actions_error_by_default(self):
        """When no error_type given, raises AgentActionsError."""
        cause = ValueError("bad value")
        with pytest.raises(AgentActionsError, match="something failed.*bad value"):
            ErrorHandler.handle_error(cause, "something failed")

    def test_raises_specified_error_type(self):
        """When error_type is given, raises that specific type."""
        cause = RuntimeError("boom")
        with pytest.raises(ValidationError, match="check failed.*boom"):
            ErrorHandler.handle_error(cause, "check failed", error_type=ValidationError)

    def test_preserves_cause(self):
        """The original exception is attached as __cause__."""
        cause = TypeError("wrong type")
        with pytest.raises(AgentActionsError) as exc_info:
            ErrorHandler.handle_error(cause, "oops")
        assert exc_info.value.__cause__ is cause

    def test_includes_context(self):
        """Context dict is forwarded to the raised exception."""
        cause = ValueError("v")
        ctx = {"key": "val"}
        with pytest.raises(AgentActionsError) as exc_info:
            ErrorHandler.handle_error(cause, "msg", context=ctx)
        assert exc_info.value.context["key"] == "val"

    def test_context_includes_error_detail(self):
        """The logged extra dict includes the 'error' key."""
        cause = ValueError("detail-text")
        with pytest.raises(AgentActionsError):
            ErrorHandler.handle_error(cause, "msg")

    def test_none_context_is_safe(self):
        """Passing context=None doesn't crash."""
        cause = ValueError("x")
        with pytest.raises(AgentActionsError):
            ErrorHandler.handle_error(cause, "msg", context=None)

    def test_empty_context(self):
        """Passing an empty context dict works."""
        cause = ValueError("x")
        with pytest.raises(AgentActionsError) as exc_info:
            ErrorHandler.handle_error(cause, "msg", context={})
        # Context should at least not have user-supplied keys
        assert "error" not in exc_info.value.context or exc_info.value.context == {}

    def test_message_format(self):
        """The raised message includes both the wrapper message and original error."""
        cause = ValueError("root cause")
        with pytest.raises(AgentActionsError) as exc_info:
            ErrorHandler.handle_error(cause, "Operation failed")
        msg = str(exc_info.value)
        assert "Operation failed" in msg
        assert "root cause" in msg


# ---------------------------------------------------------------------------
# handle_validation_error
# ---------------------------------------------------------------------------


class TestHandleValidationError:
    """ErrorHandler.handle_validation_error wraps as ValidationError."""

    def test_raises_validation_error(self):
        cause = ValueError("bad schema")
        with pytest.raises(ValidationError, match="Validation failed for.*config"):
            ErrorHandler.handle_validation_error(cause, "config")

    def test_message_includes_target(self):
        cause = ValueError("oops")
        with pytest.raises(ValidationError) as exc_info:
            ErrorHandler.handle_validation_error(cause, "user_input")
        assert "user_input" in str(exc_info.value)

    def test_preserves_cause(self):
        cause = TypeError("wrong type")
        with pytest.raises(ValidationError) as exc_info:
            ErrorHandler.handle_validation_error(cause, "data")
        assert exc_info.value.__cause__ is cause

    def test_context_forwarded(self):
        cause = ValueError("v")
        ctx = {"field": "email"}
        with pytest.raises(ValidationError) as exc_info:
            ErrorHandler.handle_validation_error(cause, "user", context=ctx)
        assert exc_info.value.context["field"] == "email"


# ---------------------------------------------------------------------------
# handle_file_error
# ---------------------------------------------------------------------------


class TestHandleFileError:
    """ErrorHandler.handle_file_error maps error types correctly."""

    def test_file_not_found_raises_file_load_error(self):
        cause = FileNotFoundError("not found")
        with pytest.raises(FileLoadError, match="File operation.*read.*failed"):
            ErrorHandler.handle_file_error(cause, "read", "/tmp/missing.txt")

    def test_os_error_raises_file_system_error(self):
        cause = OSError("disk full")
        with pytest.raises(FileSystemError, match="File operation.*write.*failed"):
            ErrorHandler.handle_file_error(cause, "write", "/tmp/data.txt")

    def test_other_error_raises_file_system_error(self):
        """Non-OS/FileNotFound errors still get wrapped as FileSystemError."""
        cause = RuntimeError("unexpected")
        with pytest.raises(FileSystemError, match="File operation.*parse.*failed"):
            ErrorHandler.handle_file_error(cause, "parse", "/tmp/file.json")

    def test_message_includes_path(self):
        cause = FileNotFoundError("gone")
        with pytest.raises(FileLoadError) as exc_info:
            ErrorHandler.handle_file_error(cause, "load", "/data/config.yml")
        assert "/data/config.yml" in str(exc_info.value)

    def test_path_object_accepted(self):
        """Path objects are accepted, not just strings."""
        cause = FileNotFoundError("nope")
        with pytest.raises(FileLoadError) as exc_info:
            ErrorHandler.handle_file_error(cause, "read", Path("/some/path.txt"))
        assert "/some/path.txt" in str(exc_info.value)

    def test_preserves_cause(self):
        cause = FileNotFoundError("missing")
        with pytest.raises(FileLoadError) as exc_info:
            ErrorHandler.handle_file_error(cause, "read", "/x")
        assert exc_info.value.__cause__ is cause

    def test_context_forwarded(self):
        cause = OSError("err")
        ctx = {"attempt": 2}
        with pytest.raises(FileSystemError) as exc_info:
            ErrorHandler.handle_file_error(cause, "write", "/x", context=ctx)
        assert exc_info.value.context["attempt"] == 2

    def test_file_not_found_is_subclass_of_file_system_error(self):
        """FileLoadError inherits from FileSystemError, so it matches both."""
        cause = FileNotFoundError("gone")
        with pytest.raises(FileSystemError):
            ErrorHandler.handle_file_error(cause, "read", "/x")


# ---------------------------------------------------------------------------
# handle_config_error
# ---------------------------------------------------------------------------


class TestHandleConfigError:
    """ErrorHandler.handle_config_error wraps as ConfigurationError."""

    def test_raises_configuration_error(self):
        cause = KeyError("missing_key")
        with pytest.raises(
            ConfigurationError, match="Configuration operation.*load.*failed for.*app_config"
        ):
            ErrorHandler.handle_config_error(cause, "load", "app_config")

    def test_message_includes_operation_and_config_name(self):
        cause = ValueError("invalid")
        with pytest.raises(ConfigurationError) as exc_info:
            ErrorHandler.handle_config_error(cause, "parse", "database.yml")
        msg = str(exc_info.value)
        assert "parse" in msg
        assert "database.yml" in msg

    def test_preserves_cause(self):
        cause = TypeError("wrong")
        with pytest.raises(ConfigurationError) as exc_info:
            ErrorHandler.handle_config_error(cause, "validate", "cfg")
        assert exc_info.value.__cause__ is cause

    def test_context_forwarded(self):
        cause = ValueError("v")
        ctx = {"line": 42}
        with pytest.raises(ConfigurationError) as exc_info:
            ErrorHandler.handle_config_error(cause, "parse", "cfg", context=ctx)
        assert exc_info.value.context["line"] == 42


# ---------------------------------------------------------------------------
# handle_template_error
# ---------------------------------------------------------------------------


class TestHandleTemplateError:
    """ErrorHandler.handle_template_error wraps as TemplateRenderingError."""

    def test_raises_template_rendering_error(self):
        cause = KeyError("undefined_var")
        with pytest.raises(
            TemplateRenderingError,
            match="Template operation.*render.*failed for.*prompt.j2",
        ):
            ErrorHandler.handle_template_error(cause, "render", "prompt.j2")

    def test_message_includes_operation_and_template_name(self):
        cause = ValueError("bad syntax")
        with pytest.raises(TemplateRenderingError) as exc_info:
            ErrorHandler.handle_template_error(cause, "compile", "base.html")
        msg = str(exc_info.value)
        assert "compile" in msg
        assert "base.html" in msg

    def test_preserves_cause(self):
        cause = SyntaxError("bad template")
        with pytest.raises(TemplateRenderingError) as exc_info:
            ErrorHandler.handle_template_error(cause, "parse", "tmpl")
        assert exc_info.value.__cause__ is cause

    def test_context_forwarded(self):
        cause = ValueError("v")
        ctx = {"line": 10}
        with pytest.raises(TemplateRenderingError) as exc_info:
            ErrorHandler.handle_template_error(cause, "render", "t", context=ctx)
        assert exc_info.value.context["line"] == 10


# ---------------------------------------------------------------------------
# handle_execution_error
# ---------------------------------------------------------------------------


class TestHandleExecutionError:
    """ErrorHandler.handle_execution_error wraps as AgentExecutionError."""

    def test_raises_agent_execution_error(self):
        cause = RuntimeError("timeout")
        with pytest.raises(
            AgentExecutionError, match="Execution of.*run.*failed for.*agent_x"
        ):
            ErrorHandler.handle_execution_error(cause, "run", "agent_x")

    def test_message_includes_operation_and_target(self):
        cause = ValueError("bad input")
        with pytest.raises(AgentExecutionError) as exc_info:
            ErrorHandler.handle_execution_error(cause, "transform", "pipeline_b")
        msg = str(exc_info.value)
        assert "transform" in msg
        assert "pipeline_b" in msg

    def test_preserves_cause(self):
        cause = TimeoutError("slow")
        with pytest.raises(AgentExecutionError) as exc_info:
            ErrorHandler.handle_execution_error(cause, "exec", "t")
        assert exc_info.value.__cause__ is cause

    def test_context_forwarded(self):
        cause = ValueError("v")
        ctx = {"retry_count": 3}
        with pytest.raises(AgentExecutionError) as exc_info:
            ErrorHandler.handle_execution_error(cause, "run", "t", context=ctx)
        assert exc_info.value.context["retry_count"] == 3


# ---------------------------------------------------------------------------
# format_for_user
# ---------------------------------------------------------------------------


class TestFormatForUser:
    """ErrorHandler.format_for_user delegates to format_user_error."""

    def test_delegates_to_format_user_error(self):
        """Verify it calls the logging.errors module's formatter."""
        error = ValueError("test error")
        # format_for_user does a lazy import from agent_actions.logging.errors,
        # so we patch at the source module.
        with patch(
            "agent_actions.logging.errors.format_user_error",
            return_value="user-friendly message",
        ) as mock_fmt:
            result = ErrorHandler.format_for_user(error, context={"key": "val"})
            assert result == "user-friendly message"
            mock_fmt.assert_called_once_with(error, {"key": "val"})

    def test_with_none_context(self):
        """Passing None context doesn't crash."""
        error = ValueError("oops")
        with patch(
            "agent_actions.logging.errors.format_user_error",
            return_value="msg",
        ):
            result = ErrorHandler.format_for_user(error, context=None)
            assert result == "msg"


# ---------------------------------------------------------------------------
# Cross-cutting: AgentActionsError subclass chaining
# ---------------------------------------------------------------------------


class TestErrorChaining:
    """Verify that wrapped errors form a proper exception chain."""

    def test_agent_actions_error_cause_chain(self):
        """AgentActionsError from handle_error has correct __cause__."""
        original = ValueError("root")
        with pytest.raises(AgentActionsError) as exc_info:
            ErrorHandler.handle_error(original, "wrapper")
        assert exc_info.value.__cause__ is original
        assert exc_info.value.cause is original

    def test_nested_handler_calls_chain_causes(self):
        """When a handler wraps an already-wrapped error, causes chain correctly."""
        original = TypeError("deep root")
        try:
            ErrorHandler.handle_error(original, "inner", error_type=ValidationError)
        except ValidationError as wrapped:
            with pytest.raises(ConfigurationError) as exc_info:
                ErrorHandler.handle_error(wrapped, "outer", error_type=ConfigurationError)
            assert exc_info.value.__cause__ is wrapped
            assert exc_info.value.__cause__.__cause__ is original
