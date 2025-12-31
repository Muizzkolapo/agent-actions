"""Unit tests for batch retry configuration."""

import pytest
from agent_actions.llm_invocation.batch.retry.batch_retry_config import (
    RetryConfig,
    RETRY_PRESETS,
    get_retry_config,
)


class TestRetryConfig:
    """Tests for RetryConfig model."""

    def test_default_values(self):
        """Test default configuration values."""
        config = RetryConfig()
        assert config.enabled is True
        assert config.max_attempts == 3

    def test_disabled_config(self):
        """Test disabled configuration."""
        config = RetryConfig.disabled()
        assert config.enabled is False
        assert config.max_attempts == 0
        assert config.is_enabled is False

    def test_is_enabled_property(self):
        """Test is_enabled property logic."""
        # Enabled with attempts
        config = RetryConfig(enabled=True, max_attempts=3)
        assert config.is_enabled is True

        # Enabled but zero attempts
        config = RetryConfig(enabled=True, max_attempts=0)
        assert config.is_enabled is False

        # Disabled
        config = RetryConfig(enabled=False, max_attempts=3)
        assert config.is_enabled is False

    def test_should_retry(self):
        """Test should_retry method."""
        config = RetryConfig(enabled=True, max_attempts=3)

        # Should retry when under max attempts
        assert config.should_retry(0) is True
        assert config.should_retry(1) is True
        assert config.should_retry(2) is True

        # Should not retry when at or over max
        assert config.should_retry(3) is False
        assert config.should_retry(4) is False

    def test_should_retry_disabled(self):
        """Test should_retry when disabled."""
        config = RetryConfig.disabled()
        assert config.should_retry(0) is False


class TestRetryConfigFromYaml:
    """Tests for RetryConfig.from_yaml parsing."""

    def test_from_yaml_none(self):
        """Test parsing None value."""
        config = RetryConfig.from_yaml(None)
        assert config.enabled is False
        assert config.max_attempts == 0

    def test_from_yaml_false(self):
        """Test parsing False value."""
        config = RetryConfig.from_yaml(False)
        assert config.enabled is False
        assert config.max_attempts == 0

    def test_from_yaml_true(self):
        """Test parsing True value."""
        config = RetryConfig.from_yaml(True)
        assert config.enabled is True
        assert config.max_attempts == 3

    def test_from_yaml_preset_default(self):
        """Test parsing 'default' preset."""
        config = RetryConfig.from_yaml("default")
        assert config.enabled is True
        assert config.max_attempts == 3

    def test_from_yaml_preset_aggressive(self):
        """Test parsing 'aggressive' preset."""
        config = RetryConfig.from_yaml("aggressive")
        assert config.enabled is True
        assert config.max_attempts == 5

    def test_from_yaml_preset_conservative(self):
        """Test parsing 'conservative' preset."""
        config = RetryConfig.from_yaml("conservative")
        assert config.enabled is True
        assert config.max_attempts == 2

    def test_from_yaml_preset_disabled(self):
        """Test parsing 'disabled' preset."""
        config = RetryConfig.from_yaml("disabled")
        assert config.enabled is False
        assert config.max_attempts == 0

    def test_from_yaml_preset_case_insensitive(self):
        """Test preset names are case insensitive."""
        config = RetryConfig.from_yaml("AGGRESSIVE")
        assert config.max_attempts == 5

    def test_from_yaml_unknown_preset_raises(self):
        """Test unknown preset raises ValueError."""
        with pytest.raises(ValueError, match="Unknown retry preset"):
            RetryConfig.from_yaml("unknown_preset")

    def test_from_yaml_dict_simple(self):
        """Test parsing simple dict config."""
        config = RetryConfig.from_yaml(
            {
                "enabled": True,
                "max_attempts": 5,
            }
        )
        assert config.enabled is True
        assert config.max_attempts == 5

    def test_from_yaml_dict_with_preset_base(self):
        """Test parsing dict with preset as base."""
        config = RetryConfig.from_yaml(
            {
                "preset": "conservative",
                "max_attempts": 4,  # Override preset's 2
            }
        )
        assert config.enabled is True
        assert config.max_attempts == 4

    def test_from_yaml_invalid_type_raises(self):
        """Test invalid type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid retry configuration type"):
            RetryConfig.from_yaml(123)


class TestGetRetryConfig:
    """Tests for get_retry_config helper function."""

    def test_none_agent_config_returns_default(self):
        """Test None agent_config returns default."""
        config = get_retry_config(None)
        assert config.enabled is True
        assert config.max_attempts == 3

    def test_no_retry_key_returns_default(self):
        """Test missing retry key returns default."""
        config = get_retry_config({"model_vendor": "openai"})
        assert config.enabled is True
        assert config.max_attempts == 3

    def test_retry_key_parsed(self):
        """Test retry key is parsed correctly."""
        config = get_retry_config({"retry": {"enabled": True, "max_attempts": 5}})
        assert config.max_attempts == 5

    def test_custom_default_used(self):
        """Test custom default config is used when no retry specified."""
        default = RetryConfig(enabled=False, max_attempts=1)
        config = get_retry_config({}, default_config=default)
        assert config.enabled is False
        assert config.max_attempts == 1


class TestRetryPresets:
    """Tests for retry presets."""

    def test_all_presets_valid(self):
        """Test all presets can be loaded."""
        for preset_name in RETRY_PRESETS:
            config = RetryConfig.from_yaml(preset_name)
            assert isinstance(config, RetryConfig)

    def test_preset_values_match_constants(self):
        """Test preset values match RETRY_PRESETS constants."""
        for preset_name, preset_values in RETRY_PRESETS.items():
            config = RetryConfig.from_yaml(preset_name)
            assert config.enabled == preset_values["enabled"]
            assert config.max_attempts == preset_values["max_attempts"]
