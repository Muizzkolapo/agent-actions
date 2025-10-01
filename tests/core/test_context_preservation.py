"""
Tests for context preservation through exception chains.

These tests verify that Phase 3 implementation correctly:
1. Preserves context through multiple levels of exception wrapping
2. Extracts root causes correctly from complex chains
3. Uses structured context dicts instead of string interpolation
4. Maintains cause links through exception chains
"""

import pytest
from agent_actions.core.exceptions import (
    AgentActionsException,
    ConfigurationError,
    ValidationError,
    FileLoadError,
    TemplateRenderingError
)
from agent_actions.core.safe_format import (
    extract_root_cause,
    get_error_chain,
    format_exception_chain_for_debug,
    safe_format_error
)
from agent_actions.core.user_errors import format_user_error


class TestContextPreservationThroughChains:
    """Test that context is preserved through exception chains."""

    def test_single_level_context_preservation(self):
        """Test context is preserved in a single exception."""
        exc = ConfigurationError(
            "Invalid config",
            context={'agent': 'test-agent', 'field': 'model'}
        )

        assert exc.context == {'agent': 'test-agent', 'field': 'model'}
        assert 'test-agent' in str(exc)

    def test_two_level_context_preservation(self):
        """Test context is preserved through 2-level exception chain."""
        # Level 1: Root cause
        root = ValueError("Model name cannot be empty")

        # Level 2: Wrap with context
        exc = ValidationError(
            f"Validation failed: {safe_format_error(root)}",
            context={'field': 'model', 'agent': 'test-agent'},
            cause=root
        )

        # Verify context is preserved
        assert exc.context == {'field': 'model', 'agent': 'test-agent'}
        assert exc.cause == root

        # Verify chain is correct
        chain = get_error_chain(exc)
        assert len(chain) == 2
        assert chain[0] == exc
        assert chain[1] == root

    def test_three_level_context_preservation(self):
        """Test context is preserved through 3-level exception chain."""
        # Level 1: Root cause (file error)
        root = FileNotFoundError("/path/to/config.yml")

        # Level 2: Wrap in FileLoadError with context
        middle = FileLoadError(
            "/path/to/config.yml",
            f"Could not read file: {safe_format_error(root)}",
            context={'operation': 'load_config'},
            cause=root
        )

        # Level 3: Wrap in ConfigurationError with more context
        top = ConfigurationError(
            f"Failed to load configuration: {safe_format_error(middle)}",
            context={'agent': 'test-agent', 'command': 'run'},
            cause=middle
        )

        # Verify each level has its context
        assert middle.context['operation'] == 'load_config'
        assert top.context['agent'] == 'test-agent'

        # Verify chain is correct
        chain = get_error_chain(top)
        assert len(chain) == 3
        assert chain[0] == top
        assert chain[1] == middle
        assert chain[2] == root

        # Verify root cause extraction
        extracted_root = extract_root_cause(top)
        assert extracted_root == root

    def test_five_level_deep_chain(self):
        """Test context preservation in very deep exception chain (like original bug)."""
        # Simulate the original cascading error scenario

        # Level 1: Original API error
        level1 = ValueError("Model 'claude-sonnet-4-20250514' not supported by this provider")

        # Level 2: Provider error
        level2 = ConfigurationError(
            f"Provider initialization failed: {safe_format_error(level1)}",
            context={'provider': 'anthropic'},
            cause=level1
        )

        # Level 3: Batch service error
        level3 = ConfigurationError(
            f"Failed to create batch provider: {safe_format_error(level2)}",
            context={'provider_type': 'anthropic', 'operation': 'create_provider'},
            cause=level2
        )

        # Level 4: Target generator error
        level4 = AgentActionsException(
            f"Error generating target: {safe_format_error(level3)}",
            context={'file_path': '/path/to/source.json', 'operation': 'generate_target'},
            cause=level3
        )

        # Level 5: Top-level run error
        level5 = AgentActionsException(
            f"Failed to run agent: {safe_format_error(level4)}",
            context={'agent': 'qanalabs-quiz-gen', 'command': 'run'},
            cause=level4
        )

        # Verify chain depth
        chain = get_error_chain(level5)
        assert len(chain) == 5

        # Verify root cause is correct
        root = extract_root_cause(level5)
        assert root == level1
        assert "not supported" in str(root)

        # Verify all context is preserved at each level
        assert level2.context['provider'] == 'anthropic'
        assert level3.context['provider_type'] == 'anthropic'
        assert level4.context['file_path'] == '/path/to/source.json'
        assert level5.context['agent'] == 'qanalabs-quiz-gen'

    def test_context_in_user_error_formatting(self):
        """Test that user error formatting includes context from exception."""
        exc = ValidationError(
            "Missing required field 'model'",
            context={'agent': 'test-agent', 'field': 'model', 'file': 'config.yml'}
        )

        formatted = format_user_error(exc, {'command': 'run'})

        # Should include context information
        assert 'test-agent' in formatted
        assert 'model' in formatted


class TestRootCauseExtraction:
    """Test root cause extraction from complex chains."""

    def test_extract_root_from_simple_chain(self):
        """Test extracting root cause from simple 2-level chain."""
        root = ValueError("Root error")
        top = RuntimeError("Wrapper error")
        top.__cause__ = root

        extracted = extract_root_cause(top)
        assert extracted == root

    def test_extract_root_from_deep_chain(self):
        """Test extracting root cause from deep chain."""
        root = ValueError("Root")
        level2 = RuntimeError("Level 2")
        level3 = TypeError("Level 3")
        level4 = ConfigurationError("Level 4")

        level2.__cause__ = root
        level3.__cause__ = level2
        level4.__cause__ = level3

        extracted = extract_root_cause(level4)
        assert extracted == root

    def test_extract_root_handles_circular_references(self):
        """Test that extraction handles circular references safely."""
        exc1 = ValueError("Error 1")
        exc2 = RuntimeError("Error 2")

        # Create circular reference
        exc1.__cause__ = exc2
        exc2.__cause__ = exc1

        # Should not infinite loop
        extracted = extract_root_cause(exc1)
        assert extracted in [exc1, exc2]  # Returns starting point when circular

    def test_extract_root_from_context_chain(self):
        """Test extraction using __context__ instead of __cause__."""
        root = ValueError("Root")
        wrapper = RuntimeError("Wrapper")
        wrapper.__context__ = root

        extracted = extract_root_cause(wrapper)
        assert extracted == root


class TestDebugChainFormatting:
    """Test debug formatting of exception chains."""

    def test_format_single_exception(self):
        """Test formatting a single exception."""
        exc = ValueError("Test error")
        formatted = format_exception_chain_for_debug(exc)

        assert "Exception Chain (1 level)" in formatted
        assert "ValueError: Test error" in formatted
        assert "(Root Cause)" in formatted

    def test_format_chain_with_context(self):
        """Test formatting chain with context at each level."""
        root = ValueError("Root error")
        wrapper = ConfigurationError(
            "Config error",
            context={'agent': 'test-agent', 'file': 'config.yml'},
            cause=root
        )

        formatted = format_exception_chain_for_debug(wrapper)

        assert "Exception Chain (2 levels)" in formatted
        assert "ConfigurationError" in formatted
        assert "ValueError" in formatted
        assert "test-agent" in formatted
        assert "config.yml" in formatted
        assert "(Root Cause)" in formatted

    def test_format_deep_chain(self):
        """Test formatting deep exception chain."""
        root = ValueError("Root")
        middle = RuntimeError("Middle")
        top = TypeError("Top")

        middle.__cause__ = root
        top.__cause__ = middle

        formatted = format_exception_chain_for_debug(top)

        assert "Exception Chain (3 levels)" in formatted
        assert "[1] TypeError: Top" in formatted
        assert "[2] RuntimeError: Middle" in formatted
        assert "[3] ValueError: Root" in formatted


class TestStructuredContextUsage:
    """Test that exceptions use structured context dicts, not string interpolation."""

    def test_exception_with_dict_context(self):
        """Test exception uses dict context instead of string interpolation."""
        exc = AgentActionsException(
            "Operation failed",
            context={
                'file_path': '/path/to/file',
                'operation': 'write',
                'file_type': '.json'
            }
        )

        # Context should be a dict, not interpolated in message
        assert isinstance(exc.context, dict)
        assert exc.context['file_path'] == '/path/to/file'
        assert exc.context['operation'] == 'write'

        # String representation should include context
        str_repr = str(exc)
        assert 'file_path' in str_repr
        assert '/path/to/file' in str_repr

    def test_exception_preserves_original_error_in_context(self):
        """Test that wrapped exceptions preserve original error details."""
        original = ValueError("Original error message")

        wrapper = AgentActionsException(
            f"Wrapper: {safe_format_error(original)}",
            context={
                'original_error_type': type(original).__name__,
                'operation': 'test_operation'
            },
            cause=original
        )

        # Original error should be accessible via cause
        assert wrapper.cause == original
        # Context should have error type
        assert wrapper.context['original_error_type'] == 'ValueError'


class TestCauseChainPreservation:
    """Test that exception chains preserve cause links properly."""

    def test_cause_chain_with_from_syntax(self):
        """Test that 'raise ... from e' preserves cause."""
        try:
            try:
                raise ValueError("Root")
            except ValueError as e:
                raise ConfigurationError("Wrapped", cause=e) from e
        except ConfigurationError as exc:
            assert exc.cause is not None
            assert isinstance(exc.__cause__, ValueError)
            assert str(exc.__cause__) == "Root"

    def test_cause_accessible_through_chain(self):
        """Test that cause is accessible at each level."""
        root = ValueError("Root")
        middle = RuntimeError("Middle")
        top = TypeError("Top")

        middle.__cause__ = root
        top.__cause__ = middle

        # Should be able to traverse chain via __cause__
        assert top.__cause__ == middle
        assert middle.__cause__ == root
        assert root.__cause__ is None


class TestRealWorldScenarios:
    """Test real-world error scenarios from the codebase."""

    def test_file_write_error_context(self):
        """Test file write error preserves context like the fixed code."""
        try:
            # Simulate file write error
            raise IOError("Permission denied")
        except IOError as e:
            wrapped = AgentActionsException(
                f"Error writing file: {safe_format_error(e)}",
                context={'file_path': '/path/to/file', 'file_type': '.json', 'operation': 'write_target'},
                cause=e
            )

            # Verify context preservation
            assert wrapped.context['file_path'] == '/path/to/file'
            assert wrapped.context['operation'] == 'write_target'
            assert wrapped.cause is not None

    def test_config_load_error_chain(self):
        """Test config loading error chain preserves context."""
        try:
            # Simulate YAML error
            raise ValueError("Invalid YAML syntax")
        except ValueError as e:
            wrapped = ConfigurationError(
                f"Error parsing YAML: {safe_format_error(e)}",
                context={'config_path': '/path/to/config.yml', 'operation': 'parse_yaml'},
                cause=e
            )

            # Verify full chain
            chain = get_error_chain(wrapped)
            assert len(chain) == 2
            assert wrapped.context['config_path'] == '/path/to/config.yml'

    def test_target_generator_error_chain(self):
        """Test target generator error preserves context like fixed code."""
        try:
            # Simulate processing error
            raise ValidationError("Invalid data format")
        except ValidationError as e:
            wrapped = AgentActionsException(
                f"Error generating target: {safe_format_error(e)}",
                context={
                    'file_path': '/source/file.json',
                    'base_directory': '/source',
                    'output_directory': '/target'
                },
                cause=e
            )

            # Verify all context is preserved
            assert wrapped.context['file_path'] == '/source/file.json'
            assert wrapped.context['base_directory'] == '/source'
            assert wrapped.context['output_directory'] == '/target'

            # Verify root cause is extractable
            root = extract_root_cause(wrapped)
            assert isinstance(root, ValidationError)
