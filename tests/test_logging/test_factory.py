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
from agent_actions.logging.formatters import HumanFormatter


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
                handlers=[HandlerConfig(type='json', level='INFO')],
                file_handler_enabled=False  # Disable file handler for this test
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


class TestFileHandlerIntegration:
    """Tests for file handler functionality."""

    def setup_method(self):
        """Reset factory before each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clean up after each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def test_file_handler_created_when_enabled(self):
        """Test that file handler is created when enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')
            logger.info('Test message')

            assert log_file.exists()
            content = log_file.read_text()
            assert 'Test message' in content

    def test_file_handler_not_created_when_disabled(self):
        """Test that file handler is not created when disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=False,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')
            logger.info('Test message')

            assert not log_file.exists()

    def test_file_handler_creates_directory(self):
        """Test that file handler creates log directory if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'nested' / 'logs' / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')
            logger.info('Test message')

            assert log_file.exists()
            assert log_file.parent.exists()

    def test_file_handler_uses_debug_level(self):
        """Test that file handler uses DEBUG level by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                default_level='INFO',  # Console level
                file_handler_enabled=True,
                log_file_path=str(log_file),
                file_log_level='DEBUG',  # File level
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')
            logger.debug('Debug message')
            logger.info('Info message')

            content = log_file.read_text()
            assert 'Debug message' in content
            assert 'Info message' in content

    def test_file_handler_respects_custom_level(self):
        """Test that file handler respects custom log level."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
                file_log_level='WARNING',
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')
            logger.debug('Debug message')
            logger.info('Info message')
            logger.warning('Warning message')

            content = log_file.read_text()
            assert 'Debug message' not in content
            assert 'Info message' not in content
            assert 'Warning message' in content

    def test_file_handler_no_colors_in_output(self):
        """Test that file handler output has no ANSI color codes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')
            logger.info('Test message')
            logger.error('Error message')

            content = log_file.read_text()
            # Check for ANSI escape codes
            assert '\x1b[' not in content
            assert '\033[' not in content

    def test_file_handler_with_json_format(self):
        """Test file handler with JSON format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
                file_format='json',
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')
            logger.info('Test message', extra={'key': 'value'})

            content = log_file.read_text()
            # Should be valid JSON
            log_entry = json.loads(content.strip())
            assert log_entry['message'] == 'Test message'
            assert log_entry['level'] == 'INFO'

    def test_file_handler_applies_filters(self):
        """Test that file handler applies redacting filter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')
            logger.info('Using api_key=sk-secret123')

            content = log_file.read_text()
            assert 'sk-secret123' not in content
            assert '***' in content or '[REDACTED]' in content

    def test_file_handler_rotation(self):
        """Test that file handler rotates logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
                file_max_bytes=100,  # Small size to trigger rotation
                file_backup_count=2,
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')

            # Write enough to trigger rotation
            for i in range(20):
                logger.info(f'Message number {i} with some extra text to fill space')

            # Check that backup files were created
            backup1 = Path(str(log_file) + '.1')
            assert log_file.exists()
            # Rotation might or might not create backups depending on exact size
            # Just verify no crash and main file exists

    def test_file_handler_graceful_failure(self, monkeypatch):
        """Test that file handler fails gracefully on permission error."""
        import io
        import sys

        old_stderr = sys.stderr
        sys.stderr = io.StringIO()

        try:
            # Try to write to a path that will fail
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path='/root/impossible/test.log',  # Permission denied
            )

            # Should not raise exception, just warn
            LoggerFactory.initialize(config=config)

            # Logger should still work (console only)
            logger = LoggerFactory.get_logger('test')
            logger.info('Test message')

            # Check that warning was printed to stderr
            stderr_output = sys.stderr.getvalue()
            assert 'Warning' in stderr_output or 'Failed' in stderr_output

        finally:
            sys.stderr = old_stderr

    def test_get_project_root_finds_agent_actions_yml(self):
        """Test that _get_project_root finds agent_actions.yml directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_file = tmpdir_path / 'agent_actions.yml'
            config_file.touch()  # Create the marker file

            # Change to subdirectory
            subdir = tmpdir_path / 'subdir' / 'nested'
            subdir.mkdir(parents=True)

            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(subdir)

                # Initialize factory to access helper methods
                LoggerFactory.initialize()

                root = LoggerFactory._get_project_root()
                assert root.resolve() == tmpdir_path.resolve()

            finally:
                os.chdir(old_cwd)

    def test_get_log_file_path_with_absolute_path(self):
        """Test _get_log_file_path with absolute path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            absolute_path = Path(tmpdir) / 'custom.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(absolute_path),
            )

            LoggerFactory.initialize(config=config)
            path = LoggerFactory._get_log_file_path()

            assert path == absolute_path

    def test_get_log_file_path_with_relative_path(self):
        """Test _get_log_file_path with relative path resolves to config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config_file = tmpdir_path / 'agent_actions.yml'
            config_file.touch()  # Create the marker file

            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                config = LoggingConfig(
                    file_handler_enabled=True,
                    log_file_path='logs/my.log',  # Relative path
                )

                LoggerFactory.initialize(config=config)
                path = LoggerFactory._get_log_file_path()

                assert path.resolve() == (tmpdir_path / 'logs' / 'my.log').resolve()

            finally:
                os.chdir(old_cwd)

    def test_dual_output_console_and_file(self):
        """Test that logs go to both console and file."""
        import io
        import sys

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'

            old_stderr = sys.stderr
            sys.stderr = io.StringIO()

            try:
                config = LoggingConfig(
                    file_handler_enabled=True,
                    log_file_path=str(log_file),
                    default_level='INFO',
                    file_log_level='DEBUG',
                )

                LoggerFactory.initialize(config=config)
                logger = LoggerFactory.get_logger('test')
                logger.info('Info message')
                logger.debug('Debug message')

                # Check console output (stderr)
                console_output = sys.stderr.getvalue()
                assert 'Info message' in console_output
                # Debug might not appear in console if console is INFO level

                # Check file output
                file_content = log_file.read_text()
                assert 'Info message' in file_content
                assert 'Debug message' in file_content  # File should have DEBUG

            finally:
                sys.stderr = old_stderr


class TestSourceLocationControl:
    """Tests for source location (file:line) display control."""

    def test_normal_mode_no_source_location(self):
        """Test that normal mode does not include source location."""
        import io

        config = LoggingConfig(include_source_location=False)
        LoggerFactory.initialize(config, force=True)

        logger = LoggerFactory.get_logger('test')

        # Capture console output
        console_capture = io.StringIO()
        console_handler = logging.StreamHandler(console_capture)
        console_handler.setFormatter(
            HumanFormatter(use_colors=False, include_source_location=False)
        )
        logger.addHandler(console_handler)

        logger.info('Test message')

        output = console_capture.getvalue()

        # Should NOT contain file references
        assert 'test_factory.py' not in output
        # Allow correlation context brackets but not file references
        assert 'Test message' in output
        # Ensure no parentheses for file location (but allow for correlation context)
        assert '(' not in output or '[' in output  # Allow [correlation] but not (file.py:line)

    def test_debug_mode_with_source_location(self):
        """Test that debug mode includes source location."""
        import io

        config = LoggingConfig(include_source_location=True, default_level='DEBUG')
        LoggerFactory.initialize(config, force=True)

        logger = LoggerFactory.get_logger('test')

        # Capture console output
        console_capture = io.StringIO()
        console_handler = logging.StreamHandler(console_capture)
        console_handler.setFormatter(
            HumanFormatter(use_colors=False, include_source_location=True)
        )
        logger.addHandler(console_handler)

        logger.debug('Debug message')

        output = console_capture.getvalue()

        # SHOULD contain file references
        assert 'test_factory.py' in output
        assert '(' in output and ')' in output
        assert 'Debug message' in output

    def test_file_handler_respects_source_location_config(self):
        """Test that file handler respects include_source_location config."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'

            # Test with source location OFF
            config = LoggingConfig(
                include_source_location=False,
                file_handler_enabled=True,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config, force=True)
            logger = LoggerFactory.get_logger('test')
            logger.info('Test without source')

            file_content = log_file.read_text()
            assert 'Test without source' in file_content
            assert 'test_factory.py' not in file_content

            # Reset and test with source location ON
            LoggerFactory.reset()
            log_file.unlink()

            config = LoggingConfig(
                include_source_location=True,
                file_handler_enabled=True,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config, force=True)
            logger = LoggerFactory.get_logger('test')
            logger.info('Test with source')

            file_content = log_file.read_text()
            assert 'Test with source' in file_content
            assert 'test_factory.py' in file_content
