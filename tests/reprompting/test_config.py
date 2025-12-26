"""Tests for RepromptConfig configuration parsing."""

import pytest
from agent_actions.reprompting.config import RepromptConfig, PRESETS


class TestRepromptConfigFromYaml:
    """Tests for RepromptConfig.from_yaml() parsing."""

    def test_from_yaml_none_disabled(self):
        """Test that None creates disabled config."""
        config = RepromptConfig.from_yaml(None)
        assert config.enabled is False

    def test_from_yaml_false_disabled(self):
        """Test that False creates disabled config."""
        config = RepromptConfig.from_yaml(False)
        assert config.enabled is False

    def test_from_yaml_true_uses_basic_preset(self):
        """Test that True creates basic preset config."""
        config = RepromptConfig.from_yaml(True)
        assert config.enabled is True
        assert config.preset == "basic"
        assert config.max_attempts == PRESETS["basic"]["max_attempts"]
        assert config.json_repair == PRESETS["basic"]["json_repair"]
        assert config.use_llm_critique == PRESETS["basic"]["use_llm_critique"]

    def test_from_yaml_string_basic(self):
        """Test that 'basic' string creates basic preset."""
        config = RepromptConfig.from_yaml("basic")
        assert config.enabled is True
        assert config.preset == "basic"
        assert config.max_attempts == 3

    def test_from_yaml_string_smart(self):
        """Test that 'smart' string creates smart preset."""
        config = RepromptConfig.from_yaml("smart")
        assert config.enabled is True
        assert config.preset == "smart"
        assert config.max_attempts == PRESETS["smart"]["max_attempts"]
        assert config.use_llm_critique == PRESETS["smart"]["use_llm_critique"]

    def test_from_yaml_string_thorough(self):
        """Test that 'thorough' string creates thorough preset."""
        config = RepromptConfig.from_yaml("thorough")
        assert config.enabled is True
        assert config.preset == "thorough"
        assert config.max_attempts == PRESETS["thorough"]["max_attempts"]
        assert config.use_llm_critique is True
        assert config.use_self_reflection is True

    def test_from_yaml_string_case_insensitive(self):
        """Test that preset names are case-insensitive."""
        config = RepromptConfig.from_yaml("SMART")
        assert config.preset == "smart"
        assert config.use_llm_critique is True

    def test_from_yaml_invalid_preset_raises(self):
        """Test that invalid preset name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            RepromptConfig.from_yaml("invalid_preset")
        assert "Unknown reprompt preset" in str(exc_info.value)

    def test_from_yaml_dict_with_preset(self):
        """Test dict config with preset specified."""
        config = RepromptConfig.from_yaml({"preset": "smart"})
        assert config.preset == "smart"
        assert config.use_llm_critique is True

    def test_from_yaml_dict_with_overrides(self):
        """Test dict config with preset and overrides."""
        config = RepromptConfig.from_yaml({
            "preset": "basic",
            "max_attempts": 5,
        })
        assert config.preset == "basic"
        assert config.max_attempts == 5  # Overridden
        assert config.json_repair is True  # From preset

    def test_from_yaml_dict_with_constraints(self):
        """Test dict config with constraints."""
        config = RepromptConfig.from_yaml({
            "preset": "basic",
            "constraints": [{"not_contains": "maze"}],
        })
        assert config.constraints == [{"not_contains": "maze"}]

    def test_from_yaml_dict_disabled(self):
        """Test dict config with enabled=False."""
        config = RepromptConfig.from_yaml({"enabled": False})
        assert config.enabled is False

    def test_from_yaml_invalid_type_raises(self):
        """Test that invalid type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            RepromptConfig.from_yaml(123)  # type: ignore
        assert "Invalid reprompt config type" in str(exc_info.value)


class TestRepromptConfigMethods:
    """Tests for RepromptConfig methods."""

    def test_should_use_critique_basic(self):
        """Test critique is never used in basic preset."""
        config = RepromptConfig.from_yaml("basic")
        assert config.should_use_critique(1) is False
        assert config.should_use_critique(3) is False
        assert config.should_use_critique(10) is False

    def test_should_use_critique_smart(self):
        """Test critique is used after critique_after_attempt in smart preset."""
        config = RepromptConfig.from_yaml("smart")
        # Smart uses critique after attempt 2 (so on attempt 3+)
        assert config.should_use_critique(1) is False
        assert config.should_use_critique(2) is True
        assert config.should_use_critique(3) is True

    def test_should_use_reflection_basic(self):
        """Test reflection is never used in basic preset."""
        config = RepromptConfig.from_yaml("basic")
        assert config.should_use_reflection(1) is False
        assert config.should_use_reflection(10) is False

    def test_should_use_reflection_thorough(self):
        """Test reflection is used in thorough preset."""
        config = RepromptConfig.from_yaml("thorough")
        # Thorough uses reflection after attempt 1 (so on attempt 2+)
        assert config.should_use_reflection(1) is True
        assert config.should_use_reflection(3) is True


class TestPresets:
    """Tests for preset definitions."""

    def test_all_presets_exist(self):
        """Test all expected presets are defined."""
        assert "basic" in PRESETS
        assert "smart" in PRESETS
        assert "thorough" in PRESETS

    def test_presets_have_required_fields(self):
        """Test all presets have required fields."""
        required_fields = [
            "max_attempts",
            "json_repair",
            "use_llm_critique",
            "use_self_reflection",
            "critique_after_attempt",
        ]
        for preset_name, preset in PRESETS.items():
            for field in required_fields:
                assert field in preset, f"Preset {preset_name} missing field {field}"

    def test_basic_preset_no_llm_features(self):
        """Test basic preset doesn't use LLM features."""
        basic = PRESETS["basic"]
        assert basic["use_llm_critique"] is False
        assert basic["use_self_reflection"] is False

    def test_smart_preset_uses_critique(self):
        """Test smart preset uses LLM critique."""
        smart = PRESETS["smart"]
        assert smart["use_llm_critique"] is True
        assert smart["use_self_reflection"] is False

    def test_thorough_preset_uses_all(self):
        """Test thorough preset uses all features."""
        thorough = PRESETS["thorough"]
        assert thorough["use_llm_critique"] is True
        assert thorough["use_self_reflection"] is True
