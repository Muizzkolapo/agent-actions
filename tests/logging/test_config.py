"""Tests for logging configuration."""

import os
from unittest.mock import patch

from agent_actions.logging.config import LoggingConfig


class TestLoggingConfigFromEnvironment:
    """Tests for LoggingConfig.from_environment()."""

    def test_default_file_handler_enabled_from_env(self):
        """Test that file handler is enabled by default from environment."""
        config = LoggingConfig.from_environment()
        assert config.file_handler.enabled is True

    def test_disable_file_handler_via_env_var(self, monkeypatch):
        """Test disabling file handler via AGENT_ACTIONS_NO_LOG_FILE."""
        monkeypatch.setenv("AGENT_ACTIONS_NO_LOG_FILE", "1")
        config = LoggingConfig.from_environment()
        assert config.file_handler.enabled is False

    def test_enable_file_handler_with_zero(self, monkeypatch):
        """Test that AGENT_ACTIONS_NO_LOG_FILE=0 keeps file handler enabled."""
        monkeypatch.setenv("AGENT_ACTIONS_NO_LOG_FILE", "0")
        config = LoggingConfig.from_environment()
        assert config.file_handler.enabled is True

    def test_custom_log_file_path_from_env(self, monkeypatch):
        """Test setting custom log file path via AGENT_ACTIONS_LOG_FILE."""
        monkeypatch.setenv("AGENT_ACTIONS_LOG_FILE", "/custom/path/my.log")
        config = LoggingConfig.from_environment()
        assert config.file_handler.path == "/custom/path/my.log"

    def test_custom_log_dir_from_env(self, monkeypatch):
        """Test setting custom log directory via AGENT_ACTIONS_LOG_DIR."""
        monkeypatch.setenv("AGENT_ACTIONS_LOG_DIR", "/custom/logs")
        config = LoggingConfig.from_environment()
        assert config.file_handler.path == "/custom/logs/agent_actions.log"

    def test_log_file_overrides_log_dir(self, monkeypatch):
        """Test that AGENT_ACTIONS_LOG_FILE takes precedence over LOG_DIR."""
        monkeypatch.setenv("AGENT_ACTIONS_LOG_FILE", "/specific/file.log")
        monkeypatch.setenv("AGENT_ACTIONS_LOG_DIR", "/general/dir")
        config = LoggingConfig.from_environment()
        assert config.file_handler.path == "/specific/file.log"

    def test_file_log_level_from_env(self, monkeypatch):
        """Test setting file log level via AGENT_ACTIONS_FILE_LOG_LEVEL."""
        monkeypatch.setenv("AGENT_ACTIONS_FILE_LOG_LEVEL", "INFO")
        config = LoggingConfig.from_environment()
        assert config.file_handler.level == "INFO"

    def test_file_log_level_defaults_to_debug(self):
        """Test that file log level defaults to DEBUG when not set."""
        config = LoggingConfig.from_environment()
        assert config.file_handler.level == "DEBUG"

    def test_invalid_file_log_level_defaults_to_debug(self, monkeypatch):
        """Test that invalid file log level defaults to DEBUG."""
        monkeypatch.setenv("AGENT_ACTIONS_FILE_LOG_LEVEL", "INVALID")
        config = LoggingConfig.from_environment()
        assert config.file_handler.level == "DEBUG"

    def test_file_log_level_case_insensitive(self, monkeypatch):
        """Test that file log level is case-insensitive."""
        monkeypatch.setenv("AGENT_ACTIONS_FILE_LOG_LEVEL", "warning")
        config = LoggingConfig.from_environment()
        assert config.file_handler.level == "WARNING"


class TestLoggingConfigFromProjectConfig:
    """Tests for LoggingConfig.from_project_config()."""

    def test_file_handler_enabled_from_yaml(self):
        """Test parsing file handler enabled from YAML."""
        project_config = {"logging": {"file": {"enabled": False}}}
        config = LoggingConfig.from_project_config(project_config)
        assert config.file_handler.enabled is False

    def test_log_file_path_from_yaml(self):
        """Test parsing log file path from YAML."""
        project_config = {"logging": {"file": {"path": "custom/logs/my_app.log"}}}
        config = LoggingConfig.from_project_config(project_config)
        assert config.file_handler.path == "custom/logs/my_app.log"

    def test_file_log_level_from_yaml(self):
        """Test parsing file log level from YAML."""
        project_config = {"logging": {"file": {"level": "WARNING"}}}
        config = LoggingConfig.from_project_config(project_config)
        assert config.file_handler.level == "WARNING"

    def test_file_max_bytes_from_yaml(self):
        """Test parsing file max bytes from YAML."""
        project_config = {
            "logging": {
                "file": {
                    "max_bytes": 5242880  # 5MB
                }
            }
        }
        config = LoggingConfig.from_project_config(project_config)
        assert config.file_handler.max_bytes == 5242880

    def test_file_backup_count_from_yaml(self):
        """Test parsing file backup count from YAML."""
        project_config = {"logging": {"file": {"backup_count": 10}}}
        config = LoggingConfig.from_project_config(project_config)
        assert config.file_handler.backup_count == 10

    def test_file_format_from_yaml(self):
        """Test parsing file format from YAML."""
        project_config = {"logging": {"file": {"format": "json"}}}
        config = LoggingConfig.from_project_config(project_config)
        assert config.file_handler.format == "json"

    def test_complete_file_config_from_yaml(self):
        """Test parsing complete file config from YAML."""
        project_config = {
            "logging": {
                "file": {
                    "enabled": True,
                    "path": "logs/agent_actions.log",
                    "level": "DEBUG",
                    "max_bytes": 10485760,
                    "backup_count": 5,
                    "format": "human",
                }
            }
        }
        config = LoggingConfig.from_project_config(project_config)
        assert config.file_handler.enabled is True
        assert config.file_handler.path == "logs/agent_actions.log"
        assert config.file_handler.level == "DEBUG"
        assert config.file_handler.max_bytes == 10485760
        assert config.file_handler.backup_count == 5
        assert config.file_handler.format == "human"


class TestLoggingConfigEdgeCases:
    """Tests for edge cases in LoggingConfig."""

    def test_missing_file_section_in_yaml(self):
        """Test that missing 'file' section in YAML uses defaults."""
        project_config = {"logging": {"level": "INFO"}}
        config = LoggingConfig.from_project_config(project_config)
        assert config.file_handler.enabled is True
        assert config.file_handler.path is None
        assert config.file_handler.level == "DEBUG"


class TestLoggingConfigDebugMode:
    """Tests for AGENT_ACTIONS_DEBUG environment variable."""

    def test_debug_env_var_enables_debug_mode(self):
        """Test that AGENT_ACTIONS_DEBUG=1 enables debug mode."""
        with patch.dict(os.environ, {"AGENT_ACTIONS_DEBUG": "1"}, clear=True):
            config = LoggingConfig.from_environment()

            assert config.include_source_location is True
            assert config.default_level == "DEBUG"

    def test_debug_env_var_zero_disables_debug_mode(self):
        """Test that AGENT_ACTIONS_DEBUG=0 disables debug mode."""
        with patch.dict(os.environ, {"AGENT_ACTIONS_DEBUG": "0"}, clear=True):
            config = LoggingConfig.from_environment()

            assert config.include_source_location is False
            assert config.default_level == "INFO"

    def test_normal_mode_without_debug_env(self):
        """Test normal mode without AGENT_ACTIONS_DEBUG."""
        with patch.dict(os.environ, {}, clear=True):
            config = LoggingConfig.from_environment()

            assert config.include_source_location is False
            assert config.default_level == "INFO"

    def test_debug_env_overrides_log_level(self):
        """Test that AGENT_ACTIONS_DEBUG=1 overrides AGENT_ACTIONS_LOG_LEVEL."""
        with patch.dict(
            os.environ,
            {"AGENT_ACTIONS_DEBUG": "1", "AGENT_ACTIONS_LOG_LEVEL": "WARNING"},
            clear=True,
        ):
            config = LoggingConfig.from_environment()

            # Debug mode should override WARNING level
            assert config.default_level == "DEBUG"
            assert config.include_source_location is True
