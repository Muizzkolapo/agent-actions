"""Tests for ServiceLogger user_facing parameter functionality."""
import logging
import io
import pytest
from agent_actions.cli.utils.service_logger import ServiceLogger


class TestServiceLoggerUserFacing:
    """Tests for ServiceLogger user_facing parameter."""

    def test_user_facing_true_logs_at_info_level(self):
        """Test that user_facing=True logs at INFO level."""
        logger = logging.getLogger('test_user_facing_info')
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        ServiceLogger.log_operation_start(logger, 'test operation', user_facing=True)
        ServiceLogger.log_operation_success(logger, 'test operation', user_facing=True)

        output = stream.getvalue()
        assert 'INFO' in output
        assert 'Starting test operation' in output
        assert 'Successfully completed test operation' in output
        assert 'DEBUG' not in output

    def test_user_facing_false_logs_at_debug_level(self):
        """Test that user_facing=False logs at DEBUG level."""
        logger = logging.getLogger('test_user_facing_false')
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        ServiceLogger.log_operation_start(logger, 'test operation', user_facing=False)
        ServiceLogger.log_operation_success(logger, 'test operation', user_facing=False)

        output = stream.getvalue()
        assert 'DEBUG' in output
        assert 'Starting test operation' in output
        assert 'Successfully completed test operation' in output
        # Should not have INFO level (only DEBUG)
        lines = output.strip().split('\n')
        for line in lines:
            assert 'INFO' not in line

    def test_default_is_user_facing_false(self):
        """Test that default behavior is user_facing=False (DEBUG level)."""
        logger = logging.getLogger('test_default_behavior')
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # No user_facing parameter - should default to False (DEBUG)
        ServiceLogger.log_operation_start(logger, 'test operation')
        ServiceLogger.log_operation_success(logger, 'test operation')

        output = stream.getvalue()
        assert 'DEBUG' in output
        assert 'Starting test operation' in output
        assert 'Successfully completed test operation' in output

    def test_user_facing_true_not_visible_at_info_threshold(self):
        """Test that user_facing=True messages are visible when logger level is INFO."""
        logger = logging.getLogger('test_info_threshold')
        logger.setLevel(logging.INFO)  # Set to INFO level
        logger.handlers.clear()

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        ServiceLogger.log_operation_start(logger, 'user facing op', user_facing=True)
        ServiceLogger.log_operation_start(logger, 'internal op', user_facing=False)

        output = stream.getvalue()
        # User-facing operation should be visible
        assert 'Starting user facing op' in output
        # Internal operation should NOT be visible (DEBUG level filtered out)
        assert 'Starting internal op' not in output

    def test_context_parameters_passed_through(self):
        """Test that additional context parameters are passed through correctly."""
        logger = logging.getLogger('test_context_params')
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(levelname)s - %(message)s - %(operation)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        ServiceLogger.log_operation_start(
            logger,
            'compile template',
            user_facing=True,
            config_path='/path/to/config.yml',
            template_dir='/path/to/templates'
        )

        output = stream.getvalue()
        assert 'INFO' in output
        assert 'Starting compile template' in output
        assert 'compile template' in output  # operation context

    def test_both_start_and_success_respect_user_facing(self):
        """Test that both log_operation_start and log_operation_success respect user_facing."""
        logger = logging.getLogger('test_both_methods')
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # User-facing operation
        ServiceLogger.log_operation_start(logger, 'render', user_facing=True)
        ServiceLogger.log_operation_success(logger, 'render', user_facing=True)

        # Internal operation
        ServiceLogger.log_operation_start(logger, 'validate', user_facing=False)
        ServiceLogger.log_operation_success(logger, 'validate', user_facing=False)

        output = stream.getvalue()
        lines = output.strip().split('\n')

        # Should have 4 lines
        assert len(lines) == 4

        # First two should be INFO (render)
        assert 'INFO' in lines[0]
        assert 'Starting render' in lines[0]
        assert 'INFO' in lines[1]
        assert 'Successfully completed render' in lines[1]

        # Last two should be DEBUG (validate)
        assert 'DEBUG' in lines[2]
        assert 'Starting validate' in lines[2]
        assert 'DEBUG' in lines[3]
        assert 'Successfully completed validate' in lines[3]
