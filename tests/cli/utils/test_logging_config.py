"""
Unit tests for the logging configuration module.
"""

import os
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from agent_actions.cli.utils.logging_config import (
    LoggingConfigurator,
    StandardFormatter,
    JSONFormatter,
    ConsoleHandler,
    RotatingFileHandler,
    LogLevelResolver,
    LogDirectoryManager,
    setup_logging
)


class TestLoggingConfig(unittest.TestCase):
    """Test cases for the logging configuration module."""
    
    def setUp(self):
        """Set up test environment."""
        # Create temporary directory for logs
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.temp_dir.name)
        
        # Clear all handlers from the root logger
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
    
    def tearDown(self):
        """Clean up test environment."""
        # Clear all handlers from the root logger
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            
        # Close the temporary directory
        self.temp_dir.cleanup()
    
    def test_log_level_resolver_valid_levels(self):
        """Test that LogLevelResolver correctly resolves valid log levels."""
        test_cases = [
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
            ("CRITICAL", logging.CRITICAL),
            ("debug", logging.DEBUG),  # Test case insensitivity
            ("Info", logging.INFO),    # Test case insensitivity
        ]
        
        for level_name, expected_level in test_cases:
            with self.subTest(level_name=level_name):
                actual_level = LogLevelResolver.get_level(level_name)
                self.assertEqual(actual_level, expected_level)
    
    def test_log_level_resolver_invalid_level(self):
        """Test that LogLevelResolver raises ValueError for invalid log levels."""
        with self.assertRaises(ValueError):
            LogLevelResolver.get_level("INVALID_LEVEL")
    
    def test_log_directory_manager_creates_directory(self):
        """Test that LogDirectoryManager creates directories as expected."""
        test_dir = self.log_dir / "test_logs"
        
        # Directory should not exist
        self.assertFalse(test_dir.exists())
        
        # Create directory
        result = LogDirectoryManager.create_directory(test_dir)
        
        # Directory should now exist and be returned
        self.assertTrue(test_dir.exists())
        self.assertEqual(result, test_dir)
    
    def test_log_directory_manager_handles_existing_directory(self):
        """Test that LogDirectoryManager handles existing directories gracefully."""
        test_dir = self.log_dir / "existing_logs"
        test_dir.mkdir()
        
        # Directory already exists
        self.assertTrue(test_dir.exists())
        
        # Should not raise an exception
        result = LogDirectoryManager.create_directory(test_dir)
        
        # Should return the existing directory
        self.assertEqual(result, test_dir)
    
    def test_standard_formatter(self):
        """Test that StandardFormatter creates a formatter with the expected format."""
        formatter = StandardFormatter().create_formatter()
        self.assertIsInstance(formatter, logging.Formatter)
    
    def test_json_formatter(self):
        """Test that JSONFormatter creates a formatter that outputs valid JSON."""
        formatter = JSONFormatter().create_formatter()
        
        # Create a log record
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test_path",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        # Format the record
        formatted = formatter.format(record)
        
        # Should be valid JSON
        data = json.loads(formatted)
        
        # Check required fields
        self.assertEqual(data["message"], "Test message")
        self.assertEqual(data["level"], "INFO")
        self.assertEqual(data["module"], "test_path")
        self.assertEqual(data["line"], 42)
    
    def test_console_handler(self):
        """Test that ConsoleHandler creates a properly configured handler."""
        formatter = StandardFormatter()
        handler = ConsoleHandler(logging.INFO, formatter).create_handler()
        
        self.assertIsInstance(handler, logging.StreamHandler)
        self.assertEqual(handler.level, logging.INFO)
    
    def test_file_handler(self):
        """Test that RotatingFileHandler creates a properly configured handler."""
        formatter = StandardFormatter()
        log_file = self.log_dir / "test.log"
        
        handler = RotatingFileHandler(
            logging.DEBUG,
            formatter,
            str(log_file),
            1024,
            3
        ).create_handler()
        
        self.assertIsInstance(handler, logging.handlers.RotatingFileHandler)
        self.assertEqual(handler.level, logging.DEBUG)
        self.assertEqual(handler.baseFilename.replace('\\', '/'), 
                         str(log_file).replace('\\', '/'))  # Normalize for Windows
        self.assertEqual(handler.maxBytes, 1024)
        self.assertEqual(handler.backupCount, 3)
    
    def test_logging_configurator_basic_setup(self):
        """Test basic setup with LoggingConfigurator."""
        log_file = self.log_dir / "basic.log"
        
        # Configure logging
        result = LoggingConfigurator() \
            .with_level("INFO") \
            .with_log_file(str(log_file)) \
            .setup()
        
        # Check result
        self.assertEqual(result["log_file"], str(log_file))
        self.assertEqual(result["file_level"], "INFO")
        self.assertEqual(result["console_level"], "WARNING")
        self.assertFalse(result["use_json"])
        
        # Check that handlers are registered with root logger
        root_logger = logging.getLogger()
        self.assertEqual(len(root_logger.handlers), 2)
        
        # Check that log file exists
        self.assertTrue(log_file.exists())
    
    def test_logging_configurator_json_formatting(self):
        """Test JSON formatting with LoggingConfigurator."""
        log_file = self.log_dir / "json.log"
        
        # Configure logging with JSON
        result = LoggingConfigurator() \
            .with_level("DEBUG") \
            .with_log_file(str(log_file)) \
            .with_json_formatting() \
            .setup()
        
        # Check result
        self.assertEqual(result["file_level"], "DEBUG")
        self.assertEqual(result["console_level"], "INFO")
        self.assertTrue(result["use_json"])
        
        # Log a test message
        test_logger = logging.getLogger("test_json")
        test_logger.debug("Test JSON message")
        
        # Check log file content
        with open(log_file, 'r') as f:
            content = f.read()
        
        # Should contain valid JSON
        data = json.loads(content)
        self.assertEqual(data["message"], "Test JSON message")
        self.assertEqual(data["level"], "DEBUG")
    
    def test_logging_configurator_console_level(self):
        """Test custom console level with LoggingConfigurator."""
        log_file = self.log_dir / "console.log"
        
        # Configure with custom console level
        result = LoggingConfigurator() \
            .with_level("WARNING") \
            .with_log_file(str(log_file)) \
            .with_console_level("ERROR") \
            .setup()
        
        # Check result
        self.assertEqual(result["file_level"], "WARNING")
        self.assertEqual(result["console_level"], "ERROR")
    
    @patch("agent_actions.cli.utils.logging_config.LoggingConfigurator")
    def test_setup_logging_function(self, mock_configurator):
        """Test the setup_logging function."""
        # Setup mock
        mock_instance = MagicMock()
        mock_configurator.return_value = mock_instance
        mock_instance.with_level.return_value = mock_instance
        mock_instance.with_log_file.return_value = mock_instance
        mock_instance.with_log_dir.return_value = mock_instance
        mock_instance.with_json_formatting.return_value = mock_instance
        mock_instance.with_console_level.return_value = mock_instance
        mock_instance.setup.return_value = {"result": "test"}
        
        # Call the function
        result = setup_logging(
            log_level="DEBUG",
            log_file="/path/to/log.log",
            use_json=True,
            console_level="ERROR"
        )
        
        # Verify calls
        mock_configurator.assert_called_once()
        mock_instance.with_level.assert_called_once_with("DEBUG")
        mock_instance.with_log_file.assert_called_once_with("/path/to/log.log")
        mock_instance.with_json_formatting.assert_called_once_with()
        mock_instance.with_console_level.assert_called_once_with("ERROR")
        mock_instance.setup.assert_called_once()
        
        # Verify result
        self.assertEqual(result, {"result": "test"})
    
    def test_setup_logging_integration(self):
        """Integration test for setup_logging function."""
        log_file = self.log_dir / "integration.log"
        
        # Setup logging
        result = setup_logging(
            log_level="INFO",
            log_file=str(log_file),
            use_json=True
        )
        
        # Verify result
        self.assertEqual(result["file_level"], "INFO")
        self.assertEqual(result["log_file"], str(log_file))
        
        # Log a test message
        logger = logging.getLogger("integration_test")
        logger.info("Integration test message")
        
        # Verify log file exists
        self.assertTrue(log_file.exists())
        
        # Check content
        with open(log_file, 'r') as f:
            content = f.read()
            
        # Should be valid JSON
        data = json.loads(content)
        self.assertEqual(data["message"], "Integration test message")


if __name__ == "__main__":
    unittest.main()