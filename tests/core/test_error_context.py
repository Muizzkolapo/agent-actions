"""
Tests for error_context module decorators and context capture.
"""

import pytest
from unittest.mock import Mock, patch
from agent_actions.core.error_context import (
    with_error_context,
    with_command_context,
    with_agent_context,
    with_file_context
)


class TestWithErrorContext:
    """Test with_error_context decorator."""

    def test_successful_function_execution(self):
        """Test decorator doesn't interfere with successful execution."""
        @with_error_context(operation="test_operation")
        def successful_function(x, y):
            return x + y

        result = successful_function(2, 3)
        assert result == 5

    def test_exception_gets_context(self):
        """Test that exceptions get context added."""
        @with_error_context(operation="test_operation", component="test_component")
        def failing_function():
            raise ValueError("Original error")

        with pytest.raises(ValueError) as exc_info:
            failing_function()

        exc = exc_info.value
        assert hasattr(exc, 'context')
        assert exc.context['operation'] == "test_operation"
        assert exc.context['component'] == "test_component"

    def test_context_includes_function_args(self):
        """Test that context includes function arguments."""
        @with_error_context(operation="process_file")
        def process_file(filename, mode="read"):
            raise RuntimeError("Processing failed")

        with pytest.raises(RuntimeError) as exc_info:
            process_file("test.txt", mode="write")

        exc = exc_info.value
        assert hasattr(exc, 'context')
        assert exc.context['filename'] == "test.txt"
        assert exc.context['mode'] == "write"

    def test_existing_context_preserved(self):
        """Test that existing exception context is preserved."""
        @with_error_context(operation="test_operation")
        def failing_function():
            exc = ValueError("Original error")
            exc.context = {"existing_key": "existing_value"}
            raise exc

        with pytest.raises(ValueError) as exc_info:
            failing_function()

        exc = exc_info.value
        assert exc.context['existing_key'] == "existing_value"
        assert exc.context['operation'] == "test_operation"

    def test_no_context_on_none_exception(self):
        """Test decorator handles functions that might return None."""
        @with_error_context(operation="test")
        def normal_function():
            return None

        result = normal_function()
        assert result is None

    def test_nested_decorators(self):
        """Test multiple error context decorators."""
        @with_error_context(component="outer")
        @with_error_context(operation="inner")
        def nested_function():
            raise ValueError("Nested error")

        with pytest.raises(ValueError) as exc_info:
            nested_function()

        exc = exc_info.value
        assert hasattr(exc, 'context')
        # Should have both contexts merged
        assert 'component' in exc.context
        assert 'operation' in exc.context

    def test_context_with_complex_args(self):
        """Test context capture with complex argument types."""
        @with_error_context(operation="process")
        def complex_function(data, config=None, *args, **kwargs):
            raise RuntimeError("Complex error")

        with pytest.raises(RuntimeError) as exc_info:
            complex_function(
                {"key": "value"},
                config={"setting": True},
                flag=True
            )

        exc = exc_info.value
        context = exc.context
        assert context['data'] == {"key": "value"}
        assert context['config'] == {"setting": True}
        assert 'args' in context
        assert context['flag'] is True

    def test_function_with_defaults(self):
        """Test context capture with default arguments."""
        @with_error_context(operation="test")
        def function_with_defaults(required, optional="default", flag=False):
            raise ValueError("Error with defaults")

        # Call with some defaults
        with pytest.raises(ValueError) as exc_info:
            function_with_defaults("required_value", flag=True)

        exc = exc_info.value
        context = exc.context
        assert context['required'] == "required_value"
        assert context['optional'] == "default"
        assert context['flag'] is True


class TestCommandContext:
    """Test with_command_context decorator."""

    def test_command_context_added(self):
        """Test command context is added to exceptions."""
        @with_command_context("init")
        def init_command(project_name):
            raise ValidationError("Invalid project name")

        with pytest.raises(ValidationError) as exc_info:
            init_command("invalid@name")

        exc = exc_info.value
        assert hasattr(exc, 'context')
        assert exc.context['command'] == "init"
        assert exc.context['project_name'] == "invalid@name"

    def test_successful_command_execution(self):
        """Test decorator doesn't affect successful execution."""
        @with_command_context("status")
        def status_command(agent):
            return f"Status for {agent}"

        result = status_command("test_agent")
        assert result == "Status for test_agent"


class TestAgentContext:
    """Test with_agent_context decorator."""

    def test_agent_context_added(self):
        """Test agent context is added to exceptions."""
        @with_agent_context
        def run_agent(agent_name, config_file):
            raise RuntimeError("Agent execution failed")

        with pytest.raises(RuntimeError) as exc_info:
            run_agent("test_agent", "config.yml")

        exc = exc_info.value
        assert hasattr(exc, 'context')
        assert exc.context['agent_name'] == "test_agent"
        assert exc.context['config_file'] == "config.yml"

    def test_agent_context_with_agent_param(self):
        """Test agent context when parameter is named 'agent'."""
        @with_agent_context
        def process_agent(agent, data):
            raise ValueError("Processing failed")

        with pytest.raises(ValueError) as exc_info:
            process_agent("my_agent", {"key": "value"})

        exc = exc_info.value
        assert exc.context['agent'] == "my_agent"


class TestFileContext:
    """Test with_file_context decorator."""

    def test_file_context_added(self):
        """Test file context is added to exceptions."""
        @with_file_context
        def read_config(file_path, encoding="utf-8"):
            raise FileNotFoundError("Config file not found")

        with pytest.raises(FileNotFoundError) as exc_info:
            read_config("/path/to/config.yml")

        exc = exc_info.value
        assert hasattr(exc, 'context')
        assert exc.context['file_path'] == "/path/to/config.yml"
        assert exc.context['encoding'] == "utf-8"

    def test_file_context_variations(self):
        """Test file context with different parameter names."""
        @with_file_context
        def process_file(filename, mode):
            raise IOError("File processing failed")

        with pytest.raises(IOError) as exc_info:
            process_file("data.txt", "r")

        exc = exc_info.value
        assert exc.context['filename'] == "data.txt"
        assert exc.context['mode'] == "r"


class TestContextMerging:
    """Test context merging across decorators."""

    def test_multiple_context_decorators(self):
        """Test using multiple context decorators together."""
        @with_command_context("run")
        @with_agent_context
        @with_file_context
        def complex_operation(agent_name, config_file, output_dir):
            raise ConfigurationError("Complex operation failed")

        with pytest.raises(ConfigurationError) as exc_info:
            complex_operation("test_agent", "config.yml", "/output")

        exc = exc_info.value
        context = exc.context
        assert context['command'] == "run"
        assert context['agent_name'] == "test_agent"
        assert context['config_file'] == "config.yml"
        assert context['output_dir'] == "/output"

    def test_context_override_behavior(self):
        """Test behavior when contexts have overlapping keys."""
        @with_error_context(operation="outer", common_key="outer_value")
        @with_error_context(operation="inner", common_key="inner_value")
        def overlapping_context():
            raise ValueError("Overlap test")

        with pytest.raises(ValueError) as exc_info:
            overlapping_context()

        exc = exc_info.value
        # Inner decorator should take precedence
        assert exc.context['common_key'] == "inner_value"


class TestThreadSafety:
    """Test thread safety of context decorators."""

    def test_concurrent_context_isolation(self):
        """Test that contexts don't interfere across concurrent calls."""
        import threading
        results = {}

        @with_error_context(operation="concurrent_test")
        def concurrent_function(thread_id):
            # Simulate some work
            import time
            time.sleep(0.01)
            raise ValueError(f"Error from thread {thread_id}")

        def run_test(thread_id):
            try:
                concurrent_function(thread_id)
            except ValueError as e:
                results[thread_id] = e.context['thread_id']

        threads = []
        for i in range(5):
            thread = threading.Thread(target=run_test, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Each thread should have its own context
        for i in range(5):
            assert results[i] == i


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_decorator_with_no_arguments(self):
        """Test decorator when function has no arguments."""
        @with_error_context(operation="no_args")
        def no_arg_function():
            raise ValueError("No args error")

        with pytest.raises(ValueError) as exc_info:
            no_arg_function()

        exc = exc_info.value
        assert exc.context['operation'] == "no_args"

    def test_decorator_with_class_methods(self):
        """Test decorators work with class methods."""
        class TestClass:
            @with_error_context(operation="method_test")
            def instance_method(self, value):
                raise RuntimeError(f"Method error with {value}")

            @classmethod
            @with_error_context(operation="class_method_test")
            def class_method(cls, value):
                raise RuntimeError(f"Class method error with {value}")

            @staticmethod
            @with_error_context(operation="static_method_test")
            def static_method(value):
                raise RuntimeError(f"Static method error with {value}")

        obj = TestClass()

        # Test instance method
        with pytest.raises(RuntimeError) as exc_info:
            obj.instance_method("test")
        assert exc_info.value.context['value'] == "test"

        # Test class method
        with pytest.raises(RuntimeError) as exc_info:
            TestClass.class_method("test")
        assert exc_info.value.context['value'] == "test"

        # Test static method
        with pytest.raises(RuntimeError) as exc_info:
            TestClass.static_method("test")
        assert exc_info.value.context['value'] == "test"

    def test_exception_without_context_attribute(self):
        """Test with exceptions that don't support context attribute."""
        @with_error_context(operation="test")
        def raises_builtin_exception():
            # Some built-in exceptions might not allow arbitrary attributes
            raise KeyboardInterrupt("User interrupted")

        # Should not crash even if context can't be attached
        with pytest.raises(KeyboardInterrupt):
            raises_builtin_exception()


# Import required for testing
from agent_actions.core.exceptions import ValidationError, ConfigurationError