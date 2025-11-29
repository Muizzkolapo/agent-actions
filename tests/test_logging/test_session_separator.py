"""Tests for session separator logging."""

import tempfile
from pathlib import Path

import pytest

from agent_actions.logging import CorrelationContext, LoggerFactory, LoggingConfig


class TestSessionSeparator:
    """Tests for session separator in log files."""

    def setup_method(self):
        """Reset before each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def teardown_method(self):
        """Clean up after each test."""
        LoggerFactory.reset()
        CorrelationContext.clear_context()

    def test_session_separator_format(self):
        """Test that session separator has correct format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')

            # Simulate session separator
            CorrelationContext.start_workflow('test_workflow')
            correlation_id = CorrelationContext.get_correlation_id()

            from datetime import datetime
            workflow_start = datetime.now()
            separator = f"====== {workflow_start.strftime('%H:%M:%S.%f')[:-3]} | {correlation_id[:8] if correlation_id else 'unknown'} ======"
            logger.info(separator)

            # Check log file content
            content = log_file.read_text()
            assert '======' in content
            assert correlation_id[:8] in content
            assert '|' in content

    def test_correlation_id_in_separator(self):
        """Test that correlation ID appears in separator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')

            CorrelationContext.start_workflow('test_workflow')
            correlation_id = CorrelationContext.get_correlation_id()

            from datetime import datetime
            workflow_start = datetime.now()
            separator = f"====== {workflow_start.strftime('%H:%M:%S.%f')[:-3]} | {correlation_id[:8]} ======"
            logger.info(separator)

            content = log_file.read_text()
            # Correlation ID (first 8 chars) should be in log
            assert correlation_id[:8] in content

    def test_timestamp_in_separator(self):
        """Test that timestamp appears in separator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')

            CorrelationContext.start_workflow('test_workflow')
            correlation_id = CorrelationContext.get_correlation_id()

            from datetime import datetime
            workflow_start = datetime.now()
            separator = f"====== {workflow_start.strftime('%H:%M:%S.%f')[:-3]} | {correlation_id[:8]} ======"
            logger.info(separator)

            content = log_file.read_text()
            # Should have timestamp format HH:MM:SS.mmm
            import re
            assert re.search(r'\d{2}:\d{2}:\d{2}\.\d{3}', content)

    def test_multiple_sessions_separated(self):
        """Test that multiple sessions are visually separated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')

            # First session
            CorrelationContext.start_workflow('workflow1')
            corr_id_1 = CorrelationContext.get_correlation_id()
            from datetime import datetime
            time1 = datetime.now()
            sep1 = f"====== {time1.strftime('%H:%M:%S.%f')[:-3]} | {corr_id_1[:8]} ======"
            logger.info(sep1)
            logger.info('Session 1 message')
            CorrelationContext.clear_context()

            # Second session
            CorrelationContext.start_workflow('workflow2')
            corr_id_2 = CorrelationContext.get_correlation_id()
            time2 = datetime.now()
            sep2 = f"====== {time2.strftime('%H:%M:%S.%f')[:-3]} | {corr_id_2[:8]} ======"
            logger.info(sep2)
            logger.info('Session 2 message')
            CorrelationContext.clear_context()

            content = log_file.read_text()
            # Should have two separators
            assert content.count('======') >= 4  # 2 at start, 2 at end of each separator

            # Should have both correlation IDs
            assert corr_id_1[:8] in content
            assert corr_id_2[:8] in content

    def test_separator_visible_in_file(self):
        """Test that separator is clearly visible when scanning file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / 'test.log'
            config = LoggingConfig(
                file_handler_enabled=True,
                log_file_path=str(log_file),
            )

            LoggerFactory.initialize(config=config)
            logger = LoggerFactory.get_logger('test')

            CorrelationContext.start_workflow('test_workflow')
            correlation_id = CorrelationContext.get_correlation_id()

            from datetime import datetime
            workflow_start = datetime.now()
            separator = f"====== {workflow_start.strftime('%H:%M:%S.%f')[:-3]} | {correlation_id[:8]} ======"
            logger.info(separator)

            logger.info('Log message 1')
            logger.info('Log message 2')

            content = log_file.read_text()
            lines = content.split('\n')

            # Find separator line
            separator_line = [line for line in lines if '======' in line][0]

            # Separator should be on its own line
            assert '======' in separator_line
            assert '|' in separator_line
