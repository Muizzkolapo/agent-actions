"""Tests for logging configuration."""

import os
from unittest.mock import patch

import pytest

from agent_actions.logging.config import (
    DEFAULT_LOG_MAX_BYTES,
    DEFAULT_LOG_RETAIN_RUNS,
    UNREAD_LOGGING_ENV_VARS,
    FileHandlerSettings,
    LoggingConfig,
    report_unread_env_vars,
)


class TestUnreadEnvVarsAreReported:
    """``report_unread_env_vars``: a set logging variable nothing reads is named on stderr."""

    @pytest.mark.parametrize("name", UNREAD_LOGGING_ENV_VARS)
    def test_a_set_unread_variable_is_named(self, name, capsys):
        with patch.dict(os.environ, {name: "1"}, clear=True):
            report_unread_env_vars()
        err = capsys.readouterr().err
        assert err.count("agent_actions: ignoring ") == 1
        assert f"ignoring {name}: not read and configures nothing; unset it" in err

    def test_a_set_but_empty_unread_variable_is_still_named(self, capsys):
        with patch.dict(os.environ, {"AGENT_ACTIONS_LOG_FILE": ""}, clear=True):
            report_unread_env_vars()
        assert "ignoring AGENT_ACTIONS_LOG_FILE:" in capsys.readouterr().err

    def test_read_and_unset_variables_are_not_named(self, capsys):
        env = {"AGENT_ACTIONS_LOG_RETAIN_RUNS": "2", "AGENT_ACTIONS_LOG_LEVEL": "INFO"}
        with patch.dict(os.environ, env, clear=True):
            report_unread_env_vars()
        assert capsys.readouterr().err == ""

    def test_an_unread_variable_changes_nothing_in_the_config(self):
        env = dict.fromkeys(UNREAD_LOGGING_ENV_VARS, "1")
        with patch.dict(os.environ, env, clear=True):
            config = LoggingConfig.from_environment()
        assert config == LoggingConfig()


class TestLoggingConfigFromProjectConfig:
    """Tests for LoggingConfig.from_project_config()."""

    def test_level_sets_the_console_level(self):
        config = LoggingConfig.from_project_config({"logging": {"level": "warning"}})
        assert config.default_level == "WARNING"

    def test_an_unknown_level_is_reported_and_info_stands(self, capsys):
        config = LoggingConfig.from_project_config({"logging": {"level": "LOUD"}})
        assert config.default_level == "INFO"
        err = capsys.readouterr().err
        assert "logging.level='LOUD'" in err
        assert "using INFO" in err

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

    @pytest.mark.parametrize(
        ("key", "value", "default"),
        [
            ("max_bytes", -1, DEFAULT_LOG_MAX_BYTES),
            ("max_bytes", "big", DEFAULT_LOG_MAX_BYTES),
            ("max_bytes", True, DEFAULT_LOG_MAX_BYTES),
            ("backup_count", 0, DEFAULT_LOG_RETAIN_RUNS),
            ("backup_count", 2.5, DEFAULT_LOG_RETAIN_RUNS),
        ],
    )
    def test_a_bad_file_integer_is_reported_and_the_default_stands(
        self, key, value, default, capsys
    ):
        config = LoggingConfig.from_project_config({"logging": {"file": {key: value}}})
        assert getattr(config.file_handler, key) == default
        err = capsys.readouterr().err
        assert f"logging.file.{key}={value!r}" in err
        assert f"using {default}" in err

    def test_a_file_key_nothing_reads_is_reported(self, capsys):
        """``file.path`` and friends configure nothing: the run log always goes to agent_io/logs."""
        project_config = {
            "logging": {
                "file": {
                    "enabled": False,
                    "path": "custom/logs/my_app.log",
                    "level": "WARNING",
                    "format": "json",
                    "backup_count": 7,
                }
            }
        }
        config = LoggingConfig.from_project_config(project_config)
        assert config.file_handler.backup_count == 7
        assert config.file_handler == FileHandlerSettings(backup_count=7)
        err = capsys.readouterr().err
        for key in ("enabled", "path", "level", "format"):
            assert f"ignoring logging.file.{key}:" in err
        assert "logging.file.backup_count" not in err

    def test_a_logging_key_nothing_reads_is_reported(self, capsys):
        project_config = {"logging": {"level": "DEBUG", "include_source_location": True}}
        config = LoggingConfig.from_project_config(project_config)
        assert config.default_level == "DEBUG"
        err = capsys.readouterr().err
        assert "ignoring logging.include_source_location:" in err
        assert "keys read under logging: file, level, module_levels" in err
        assert "logging.level" not in err

    @pytest.mark.parametrize("block", ["WARNING", ["level"], 3])
    def test_a_logging_block_that_is_not_a_mapping_is_reported(self, block, capsys):
        config = LoggingConfig.from_project_config({"logging": block})
        assert config == LoggingConfig()
        err = capsys.readouterr().err
        assert "ignoring logging: expected a mapping" in err

    def test_a_file_block_that_is_not_a_mapping_is_reported(self, capsys):
        config = LoggingConfig.from_project_config({"logging": {"file": "logs/app.log"}})
        assert config.file_handler == FileHandlerSettings()
        assert "ignoring logging.file: expected a mapping" in capsys.readouterr().err

    def test_no_logging_block_gives_the_defaults_without_a_report(self, capsys):
        config = LoggingConfig.from_project_config({"schema_path": "schema"})
        assert config == LoggingConfig()
        assert capsys.readouterr().err == ""

    def test_module_levels_parsed_from_yaml(self):
        """``module_levels`` mapping is parsed from YAML."""
        project_config = {
            "logging": {
                "module_levels": {"httpx": "INFO", "transformers": "ERROR"},
            }
        }
        config = LoggingConfig.from_project_config(project_config)
        assert config.module_levels == {"httpx": "INFO", "transformers": "ERROR"}

    def test_module_levels_non_dict_falls_back_with_stderr_warning(self, capsys):
        """A non-dict ``module_levels`` value must not crash init AND must warn."""
        project_config = {"logging": {"module_levels": "WARNING"}}
        config = LoggingConfig.from_project_config(project_config)
        assert config.module_levels == {}

        err = capsys.readouterr().err
        assert "module_levels" in err
        assert "dict" in err

    def test_invalid_module_levels_are_reported_and_dropped_at_resolution(self, capsys):
        """Each init re-applies the config, so a bad entry is reported here, once."""
        project_config = {
            "logging": {
                "module_levels": {
                    "httpx": True,
                    "transformers": 20,
                    42: "INFO",
                    "agent_actions.llm": "ERROR",
                    "my_custom_lib": "warn",
                }
            }
        }
        config = LoggingConfig.from_project_config(project_config)
        assert config.module_levels == {"my_custom_lib": "WARNING"}

        err = capsys.readouterr().err
        for name in ("'httpx'", "'transformers'", "42", "'agent_actions.llm'"):
            assert f"ignoring logging.module_levels[{name}]" in err
        assert "my_custom_lib" not in err


class TestLoggingConfigEdgeCases:
    """Tests for edge cases in LoggingConfig."""

    def test_missing_file_section_in_yaml(self):
        """Test that missing 'file' section in YAML uses defaults."""
        project_config = {"logging": {"level": "INFO"}}
        config = LoggingConfig.from_project_config(project_config)
        assert config.file_handler == FileHandlerSettings()


class TestLoggingConfigDebugMode:
    """Tests for AGENT_ACTIONS_DEBUG environment variable."""

    def test_debug_env_var_enables_debug_mode(self):
        """Test that AGENT_ACTIONS_DEBUG=1 enables debug mode."""
        with patch.dict(os.environ, {"AGENT_ACTIONS_DEBUG": "1"}, clear=True):
            config = LoggingConfig.from_environment()

            assert config.default_level == "DEBUG"

    def test_debug_env_var_zero_disables_debug_mode(self):
        """Test that AGENT_ACTIONS_DEBUG=0 disables debug mode."""
        with patch.dict(os.environ, {"AGENT_ACTIONS_DEBUG": "0"}, clear=True):
            config = LoggingConfig.from_environment()

            assert config.default_level == "INFO"

    def test_normal_mode_without_debug_env(self):
        """Test normal mode without AGENT_ACTIONS_DEBUG."""
        with patch.dict(os.environ, {}, clear=True):
            config = LoggingConfig.from_environment()

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


class TestEnvironmentOverlaysProjectConfig:
    """``from_environment(base)``: an unset variable keeps the project value, a set one wins."""

    @pytest.fixture
    def base(self):
        return LoggingConfig.from_project_config(
            {
                "logging": {
                    "level": "WARNING",
                    "module_levels": {"httpx": "INFO"},
                    "file": {"max_bytes": 1024, "backup_count": 2},
                }
            }
        )

    def test_unset_variables_keep_the_project_values(self, base):
        with patch.dict(os.environ, {}, clear=True):
            config = LoggingConfig.from_environment(base)
        assert config.default_level == "WARNING"
        assert config.module_levels == {"httpx": "INFO"}
        assert config.file_handler.max_bytes == 1024
        assert config.file_handler.backup_count == 2

    def test_set_variables_win_over_the_project_values(self, base):
        env = {
            "AGENT_ACTIONS_LOG_LEVEL": "ERROR",
            "AGENT_ACTIONS_LOG_MAX_BYTES": "4096",
            "AGENT_ACTIONS_LOG_RETAIN_RUNS": "9",
        }
        with patch.dict(os.environ, env, clear=True):
            config = LoggingConfig.from_environment(base)
        assert config.default_level == "ERROR"
        assert config.file_handler.max_bytes == 4096
        assert config.file_handler.backup_count == 9
        assert config.module_levels == {"httpx": "INFO"}

    def test_debug_wins_over_a_project_level(self, base):
        with patch.dict(os.environ, {"AGENT_ACTIONS_DEBUG": "1"}, clear=True):
            config = LoggingConfig.from_environment(base)
        assert config.default_level == "DEBUG"

    def test_an_invalid_variable_falls_back_to_the_project_value(self, base, capsys):
        env = {"AGENT_ACTIONS_LOG_LEVEL": "LOUD", "AGENT_ACTIONS_LOG_RETAIN_RUNS": "0"}
        with patch.dict(os.environ, env, clear=True):
            config = LoggingConfig.from_environment(base)
        assert config.default_level == "WARNING"
        assert config.file_handler.backup_count == 2
        assert "using 2" in capsys.readouterr().err

    def test_the_base_is_not_mutated(self, base):
        with patch.dict(os.environ, {"AGENT_ACTIONS_LOG_LEVEL": "ERROR"}, clear=True):
            config = LoggingConfig.from_environment(base)
        config.module_levels["urllib3"] = "DEBUG"
        assert base.default_level == "WARNING"
        assert base.module_levels == {"httpx": "INFO"}
