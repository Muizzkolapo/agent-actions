"""Tests for config_fields mutable-default, deep-copy safety, and RunMode coercion."""

import pytest

from agent_actions.config.types import RunMode
from agent_actions.output.response.config_fields import (
    SIMPLE_CONFIG_FIELDS,
    get_default,
    inherit_simple_fields,
)
from agent_actions.output.response.expander import ActionExpander
from agent_actions.validation.action_validators.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationContext,
)


class TestGetDefault:
    """Tests for get_default() — the single source of truth accessor."""

    def test_returns_known_field_value(self):
        """get_default() returns the canonical value for a known field."""
        assert get_default("kind") == "llm"
        assert get_default("granularity") == "record"
        assert get_default("json_mode") is True
        assert get_default("is_operational") is True
        assert get_default("run_mode") == RunMode.ONLINE
        assert get_default("output_field") == "raw_response"
        assert get_default("max_execution_time") == 300

    def test_returns_none_for_required_fields(self):
        """Required fields (model_vendor, model_name, api_key) default to None."""
        assert get_default("model_vendor") is None
        assert get_default("model_name") is None
        assert get_default("api_key") is None

    def test_returns_chunk_defaults(self):
        """Chunk config fields return canonical defaults."""
        assert get_default("chunk_size") == 300
        assert get_default("chunk_overlap") == 10
        assert get_default("tokenizer_model") == "cl100k_base"
        assert get_default("split_method") == "tiktoken"

    def test_unknown_field_raises_key_error(self):
        """get_default() raises KeyError with descriptive message for unknown fields."""
        with pytest.raises(KeyError, match="Unknown config field: 'nonexistent'"):
            get_default("nonexistent")

    def test_consistent_with_simple_config_fields(self):
        """get_default() returns the same values as direct SIMPLE_CONFIG_FIELDS access."""
        for field, expected in SIMPLE_CONFIG_FIELDS.items():
            assert get_default(field) is expected


class TestMutableDefaults:
    """Verify that mutable defaults cannot leak state across agents."""

    def test_constraints_default_is_immutable(self):
        """constraints default must be a tuple so accidental mutation fails fast."""
        assert isinstance(SIMPLE_CONFIG_FIELDS["constraints"], tuple)

    def test_inherit_deep_copies_list_from_action(self):
        """Lists coming from action config must be independent copies."""
        shared_list = ["no_pii"]
        action = {"constraints": shared_list}
        agent_a: dict = {}
        agent_b: dict = {}

        inherit_simple_fields(agent_a, action, {})
        inherit_simple_fields(agent_b, action, {})

        # Mutating one agent's constraints must not affect the other
        agent_a["constraints"].append("extra")
        assert "extra" not in agent_b["constraints"]
        assert "extra" not in shared_list

    def test_inherit_deep_copies_dict_from_defaults(self):
        """Dicts coming from defaults must be independent copies."""
        shared_dict = {"retry": {"max_retries": 3, "delay": 1}}
        defaults = {"retry": shared_dict["retry"]}
        agent_a: dict = {}
        agent_b: dict = {}

        inherit_simple_fields(agent_a, {}, defaults)
        inherit_simple_fields(agent_b, {}, defaults)

        agent_a["retry"]["max_retries"] = 99
        assert agent_b["retry"]["max_retries"] == 3

    def test_inherit_uses_tuple_default_when_no_override(self):
        """When neither action nor defaults provide constraints, the tuple default is used."""
        agent: dict = {}
        inherit_simple_fields(agent, {}, {})
        # Tuple default — immutable, no cross-agent risk
        assert agent["constraints"] == ()

    def test_inherit_scalar_values_unchanged(self):
        """Scalars (str, int, bool, None) should pass through without copy overhead."""
        action = {"model_vendor": "openai", "temperature": 0.7, "json_mode": False}
        agent: dict = {}
        inherit_simple_fields(agent, action, {})

        assert agent["model_vendor"] == "openai"
        assert agent["temperature"] == 0.7
        assert agent["json_mode"] is False


class TestRunModeCoercion:
    """Verify run_mode is coerced to RunMode enum from raw YAML strings."""

    def test_uppercase_run_mode_coerced_to_enum(self):
        """Raw YAML string 'BATCH' (uppercase) must be coerced to RunMode.BATCH."""
        agent: dict = {}
        inherit_simple_fields(agent, {"run_mode": "BATCH"}, {})
        assert agent["run_mode"] == RunMode.BATCH
        assert isinstance(agent["run_mode"], RunMode)

    def test_mixed_case_run_mode_coerced(self):
        """Raw YAML string 'Batch' (mixed-case) must be coerced to RunMode.BATCH."""
        agent: dict = {}
        inherit_simple_fields(agent, {"run_mode": "Batch"}, {})
        assert agent["run_mode"] == RunMode.BATCH

    def test_lowercase_run_mode_coerced(self):
        """Raw YAML string 'batch' (lowercase) must be coerced to RunMode.BATCH."""
        agent: dict = {}
        inherit_simple_fields(agent, {"run_mode": "batch"}, {})
        assert agent["run_mode"] == RunMode.BATCH
        assert isinstance(agent["run_mode"], RunMode)

    def test_default_run_mode_is_online_enum(self):
        """Default run_mode from SIMPLE_CONFIG_FIELDS must be RunMode.ONLINE."""
        agent: dict = {}
        inherit_simple_fields(agent, {}, {})
        assert agent["run_mode"] == RunMode.ONLINE
        assert isinstance(agent["run_mode"], RunMode)

    def test_run_mode_from_defaults_coerced(self):
        """run_mode from defaults dict (uppercase) must be coerced."""
        agent: dict = {}
        inherit_simple_fields(agent, {}, {"run_mode": "BATCH"})
        assert agent["run_mode"] == RunMode.BATCH

    def test_run_mode_already_enum_unchanged(self):
        """RunMode enum value passed through action dict must not be re-constructed."""
        agent: dict = {}
        inherit_simple_fields(agent, {"run_mode": RunMode.BATCH}, {})
        assert agent["run_mode"] is RunMode.BATCH


class TestRunModeEnumContract:
    """Verify RunMode enum construction contract."""

    def test_invalid_value_raises_value_error(self):
        """RunMode('invalid') must raise ValueError."""
        import pytest

        with pytest.raises(ValueError):
            RunMode("invalid")

    def test_realtime_rejected(self):
        """RunMode('realtime') must raise ValueError — not a valid mode."""
        import pytest

        with pytest.raises(ValueError):
            RunMode("realtime")


class TestIsOperationalFromConfig:
    """Verify is_operational is respected from action/defaults config."""

    def test_is_operational_false_from_action(self):
        """Action-level is_operational: false must propagate to agent."""
        action = {
            "name": "disabled_action",
            "model_vendor": "openai",
            "model_name": "gpt-4o",
            "api_key": "test-key",
        }
        defaults = {}
        agent = {"agent_type": "disabled_action", "name": "disabled_action"}

        result = ActionExpander._create_agent_from_action(
            {**action, "is_operational": False}, defaults, agent, lambda x: x
        )
        assert result["is_operational"] is False

    def test_is_operational_true_by_default(self):
        """Without explicit config, is_operational defaults to True."""
        action = {
            "name": "enabled_action",
            "model_vendor": "openai",
            "model_name": "gpt-4o",
            "api_key": "test-key",
        }
        defaults = {}
        agent = {"agent_type": "enabled_action", "name": "enabled_action"}

        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["is_operational"] is True

    def test_is_operational_false_from_defaults(self):
        """Defaults-level is_operational: false must propagate when action doesn't override."""
        action = {
            "name": "default_disabled",
            "model_vendor": "openai",
            "model_name": "gpt-4o",
            "api_key": "test-key",
        }
        defaults = {"is_operational": False}
        agent = {"agent_type": "default_disabled", "name": "default_disabled"}

        result = ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)
        assert result["is_operational"] is False


class TestVendorCompatibilityValidatorRunModeCoercion:
    """Verify VendorCompatibilityValidator coerces raw run_mode strings to RunMode."""

    def test_uppercase_batch_triggers_batch_validation(self):
        """Uppercase 'BATCH' run_mode must be coerced and trigger batch vendor checks."""
        context = ActionEntryValidationContext(
            entry={"run_mode": "BATCH", "model_vendor": "openai"},
            agent_name_context="test_agent",
        )
        validator = VendorCompatibilityValidator()
        result = validator.validate(context)
        assert not result.errors

    def test_uppercase_batch_with_invalid_vendor_warns(self):
        """Uppercase 'BATCH' with unsupported vendor must produce warning."""
        context = ActionEntryValidationContext(
            entry={"run_mode": "BATCH", "model_vendor": "unknown_vendor"},
            agent_name_context="test_agent",
        )
        validator = VendorCompatibilityValidator()
        result = validator.validate(context)
        assert len(result.warnings) == 1
        assert "unknown_vendor" in result.warnings[0]

    def test_online_mode_skips_batch_validation(self):
        """Online mode (any case) must not trigger batch vendor checks."""
        context = ActionEntryValidationContext(
            entry={"run_mode": "ONLINE", "model_vendor": "unknown_vendor"},
            agent_name_context="test_agent",
        )
        validator = VendorCompatibilityValidator()
        result = validator.validate(context)
        assert not result.errors
        assert not result.warnings
