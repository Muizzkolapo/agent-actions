"""Tests for LoggerFactory."""

import json
import logging
import tempfile
from pathlib import Path

import pytest

from agent_actions.logging import (
    CorrelationContext,
    HandlerConfig,
    LoggerFactory,
    LoggingConfig,
)


class CaptureHandler(logging.Handler):
    """Handler that captures log records for testing."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def clear(self):
        self.records.clear()


class TestLoggerFactoryInitialization:
    """Tests for LoggerFactory initialization."""

    def setup_method(self):
        """Reset factory before each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clean up after each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def test_initialize_sets_initialized_flag(self):
        """Test that initialize sets the initialized flag."""
        assert not LoggerFactory.is_initialized()

        LoggerFactory.initialize()

        assert LoggerFactory.is_initialized()

    def test_initialize_only_runs_once(self):
        """Test that initialize only runs once by default."""
        LoggerFactory.initialize()
        config1 = LoggerFactory.get_config()

        # Try to initialize again with different config
        new_config = LoggingConfig(default_level='DEBUG')
        LoggerFactory.initialize(config=new_config)

        # Should still have original config
        assert LoggerFactory.get_config() is config1

    def test_initialize_force_reinitializes(self):
        """Test that force=True allows reinitialization."""
        LoggerFactory.initialize()

        new_config = LoggingConfig(default_level='DEBUG')
        LoggerFactory.initialize(config=new_config, force=True)

        assert LoggerFactory.get_config() is new_config
        assert LoggerFactory.get_config().default_level == 'DEBUG'

    def test_initialize_uses_default_config(self):
        """Test that initialize uses defaults when no config provided."""
        LoggerFactory.initialize()

        config = LoggerFactory.get_config()
        assert config is not None
        assert config.default_level == 'INFO'  # Default level

    def test_initialize_with_custom_config(self):
        """Test initialize with custom configuration."""
        config = LoggingConfig(
            default_level='WARNING',
            include_timestamps=False,
        )

        LoggerFactory.initialize(config=config)

        assert LoggerFactory.get_config().default_level == 'WARNING'
        assert LoggerFactory.get_config().include_timestamps is False

    def test_reset_clears_state(self):
        """Test that reset clears factory state."""
        LoggerFactory.initialize()
        assert LoggerFactory.is_initialized()

        LoggerFactory.reset()

        assert not LoggerFactory.is_initialized()
        assert LoggerFactory.get_config() is None


class TestLoggerFactoryGetLogger:
    """Tests for LoggerFactory.get_logger()."""

    def setup_method(self):
        """Reset factory before each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clean up after each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def test_get_logger_auto_initializes(self):
        """Test that get_logger auto-initializes if needed."""
        assert not LoggerFactory.is_initialized()

        logger = LoggerFactory.get_logger('test')

        assert LoggerFactory.is_initialized()
        assert logger is not None

    def test_get_logger_returns_namespaced_logger(self):
        """Test that get_logger returns logger under agent_actions namespace."""
        LoggerFactory.initialize()

        logger = LoggerFactory.get_logger('mymodule')

        assert logger.name == 'agent_actions.mymodule'

    def test_get_logger_preserves_full_namespace(self):
        """Test that full namespace is preserved if already prefixed."""
        LoggerFactory.initialize()

        logger = LoggerFactory.get_logger('agent_actions.custom.module')

        assert logger.name == 'agent_actions.custom.module'

    def test_get_logger_returns_same_logger_for_same_name(self):
        """Test that get_logger returns same logger instance for same name."""
        LoggerFactory.initialize()

        logger1 = LoggerFactory.get_logger('test')
        logger2 = LoggerFactory.get_logger('test')

        assert logger1 is logger2


class TestLoggerFactoryLevelControl:
    """Tests for LoggerFactory level control."""

    def setup_method(self):
        """Reset factory before each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clean up after each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def test_set_level_changes_root_level(self):
        """Test that set_level changes root logger level."""
        LoggerFactory.initialize()

        LoggerFactory.set_level('DEBUG')

        root = logging.getLogger('agent_actions')
        assert root.level == logging.DEBUG

    def test_set_level_changes_specific_logger(self):
        """Test that set_level can change specific logger level."""
        LoggerFactory.initialize()

        LoggerFactory.set_level('DEBUG', 'mymodule')

        logger = logging.getLogger('agent_actions.mymodule')
        assert logger.level == logging.DEBUG

    def test_set_debug_enables_debug(self):
        """Test that set_debug(True) enables DEBUG level."""
        LoggerFactory.initialize()

        LoggerFactory.set_debug(True)

        root = logging.getLogger('agent_actions')
        assert root.level == logging.DEBUG

    def test_set_debug_disables_debug(self):
        """Test that set_debug(False) sets INFO level."""
        config = LoggingConfig(default_level='DEBUG')
        LoggerFactory.initialize(config=config)

        LoggerFactory.set_debug(False)

        root = logging.getLogger('agent_actions')
        assert root.level == logging.INFO


class TestLoggerFactoryContextInjection:
    """Tests for context injection through LoggerFactory."""

    def setup_method(self):
        """Reset factory before each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clean up after each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def test_logs_include_correlation_id(self):
        """Test that logs include correlation_id when context is set."""
        LoggerFactory.initialize()
        capture = CaptureHandler()
        logging.getLogger('agent_actions').addHandler(capture)

        ctx = CorrelationContext.start_workflow('test-workflow')
        logger = LoggerFactory.get_logger('test')
        logger.info('Test message')

        assert len(capture.records) == 1
        assert capture.records[0].correlation_id == ctx.correlation_id

    def test_logs_include_workflow_name(self):
        """Test that logs include workflow_name when context is set."""
        LoggerFactory.initialize()
        capture = CaptureHandler()
        logging.getLogger('agent_actions').addHandler(capture)

        CorrelationContext.start_workflow('my-workflow')
        logger = LoggerFactory.get_logger('test')
        logger.info('Test message')

        assert capture.records[0].workflow_name == 'my-workflow'

    def test_logs_include_agent_info(self):
        """Test that logs include agent info when set."""
        LoggerFactory.initialize()
        capture = CaptureHandler()
        logging.getLogger('agent_actions').addHandler(capture)

        CorrelationContext.start_workflow('test-workflow')
        CorrelationContext.set_agent('my-agent', 2)
        logger = LoggerFactory.get_logger('test')
        logger.info('Test message')

        assert capture.records[0].agent_name == 'my-agent'
        assert capture.records[0].agent_index == 2

    def test_logs_without_context_have_empty_fields(self):
        """Test that logs without context have empty context fields."""
        LoggerFactory.initialize()
        capture = CaptureHandler()
        logging.getLogger('agent_actions').addHandler(capture)

        logger = LoggerFactory.get_logger('test')
        logger.info('Test message')

        assert capture.records[0].correlation_id == ''
        assert capture.records[0].agent_name == ''


class TestLoggerFactoryHandlerConfig:
    """Tests for handler configuration."""

    def setup_method(self):
        """Reset factory before each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clean up after each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def test_console_handler_created(self):
        """Test that console handler is created."""
        config = LoggingConfig(
            handlers=[HandlerConfig(type='console', level='INFO')]
        )
        LoggerFactory.initialize(config=config)

        root = logging.getLogger('agent_actions')
        handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]

        assert len(handlers) >= 1

    def test_file_handler_created(self):
        """Test that file handler is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                handlers=[HandlerConfig(type='file', level='INFO', file_path=log_path)]
            )
            LoggerFactory.initialize(config=config)

            # Log something
            logger = LoggerFactory.get_logger('test')
            logger.info('Test message')

            # Verify file was created
            assert log_path.exists()

    def test_json_handler_outputs_json(self):
        """Test that JSON handler outputs valid JSON."""
        import io
        import sys

        # Capture stderr
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()

        try:
            config = LoggingConfig(
                handlers=[HandlerConfig(type='json', level='INFO')]
            )
            LoggerFactory.initialize(config=config)

            logger = LoggerFactory.get_logger('test')
            logger.info('Test message')

            output = sys.stderr.getvalue()
            # Parse the JSON to verify it's valid
            data = json.loads(output.strip())
            assert data['message'] == 'Test message'

        finally:
            sys.stderr = old_stderr

    def test_handler_level_is_respected(self):
        """Test that handler level filters messages."""
        LoggerFactory.reset()

        config = LoggingConfig(
            default_level='DEBUG',
            handlers=[HandlerConfig(type='console', level='WARNING')],
        )
        LoggerFactory.initialize(config=config)

        capture = CaptureHandler()
        capture.setLevel(logging.WARNING)
        logging.getLogger('agent_actions').addHandler(capture)

        logger = LoggerFactory.get_logger('test')
        logger.debug('Debug message')
        logger.info('Info message')
        logger.warning('Warning message')

        # Only warning should be captured by the WARNING-level handler
        warning_records = [r for r in capture.records if r.levelno >= logging.WARNING]
        assert len(warning_records) == 1
        assert warning_records[0].getMessage() == 'Warning message'


class TestLoggerFactoryModuleLevels:
    """Tests for module-specific level configuration."""

    def setup_method(self):
        """Reset factory before each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clean up after each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def test_module_level_is_set(self):
        """Test that module-specific levels are applied."""
        config = LoggingConfig(
            default_level='INFO',
            module_levels={'agent_actions.verbose': 'DEBUG'},
        )
        LoggerFactory.initialize(config=config)

        verbose_logger = logging.getLogger('agent_actions.verbose')
        assert verbose_logger.level == logging.DEBUG

    def test_module_level_overrides_default(self):
        """Test that module level can override default."""
        config = LoggingConfig(
            default_level='DEBUG',
            module_levels={'agent_actions.quiet': 'ERROR'},
        )
        LoggerFactory.initialize(config=config)

        quiet_logger = logging.getLogger('agent_actions.quiet')
        assert quiet_logger.level == logging.ERROR


class TestLoggerFactoryIntegration:
    """Integration tests for full logging workflow."""

    def setup_method(self):
        """Reset factory before each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clean up after each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def test_full_workflow_logging(self):
        """Test logging through a simulated workflow execution."""
        LoggerFactory.initialize()
        capture = CaptureHandler()
        logging.getLogger('agent_actions').addHandler(capture)

        # Simulate workflow start
        ctx = CorrelationContext.start_workflow('test-workflow')
        workflow_logger = LoggerFactory.get_logger('orchestration.workflow')
        workflow_logger.info('Starting workflow')

        # Simulate agent execution
        CorrelationContext.set_agent('agent-1', 0)
        agent_logger = LoggerFactory.get_logger('orchestration.executor')
        agent_logger.info('Executing agent')
        agent_logger.debug('Agent details')

        # Simulate second agent
        CorrelationContext.set_agent('agent-2', 1)
        agent_logger.info('Executing second agent')

        # Verify all logs have same correlation ID
        correlation_ids = {r.correlation_id for r in capture.records}
        assert len(correlation_ids) == 1
        assert ctx.correlation_id in correlation_ids

        # Verify agent names were updated
        agent_names = [r.agent_name for r in capture.records if r.agent_name]
        assert 'agent-1' in agent_names
        assert 'agent-2' in agent_names

    def test_exception_logging(self):
        """Test that exceptions are logged with context."""
        LoggerFactory.initialize()
        capture = CaptureHandler()
        logging.getLogger('agent_actions').addHandler(capture)

        CorrelationContext.start_workflow('test-workflow')
        logger = LoggerFactory.get_logger('test')

        try:
            raise ValueError('Test error')
        except ValueError:
            logger.exception('An error occurred')

        assert len(capture.records) == 1
        assert capture.records[0].exc_info is not None
        assert capture.records[0].exc_info[0] is ValueError

    def test_redaction_in_logs(self):
        """Test that sensitive data is redacted."""
        import io
        import sys

        old_stderr = sys.stderr
        sys.stderr = io.StringIO()

        try:
            LoggerFactory.initialize()

            logger = LoggerFactory.get_logger('test')
            logger.info('Using api_key=sk-secret123 for request')

            output = sys.stderr.getvalue()
            assert 'sk-secret123' not in output
            assert '***' in output

        finally:
            sys.stderr = old_stderr
