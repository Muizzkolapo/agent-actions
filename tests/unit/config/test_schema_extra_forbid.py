"""Tests for extra='forbid' on ActionConfig and DefaultsConfig.

Validates that Pydantic natively rejects unknown keys, accepts all valid
action-level and defaults-level keys, enforces proper types, and handles
Union types correctly.
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, DefaultsConfig
from agent_actions.errors import ConfigValidationError


class TestActionConfigForbidsUnknownKeys:
    """ActionConfig with extra='forbid' rejects unrecognized keys."""

    def test_unknown_guard_subkey_raises_via_field_validator(self):
        data = {
            "name": "test",
            "intent": "test",
            "guard": {"condition": "true", "on_falsee": "skip"},
        }
        with pytest.raises(ConfigValidationError, match="on_falsee"):
            ActionConfig.model_validate(data)

    def test_version_context_accepted_via_alias(self):
        data = {"name": "a", "intent": "i", "_version_context": {"key": "val"}}
        config = ActionConfig.model_validate(data)
        assert config.version_context == {"key": "val"}

    # --- retry / reprompt mapping validation ---

    def test_retry_false_converts_to_none(self):
        """retry: false (disabled) is accepted and converted to None."""
        data = {"name": "a", "intent": "i", "retry": False}
        config = ActionConfig.model_validate(data)
        assert config.retry is None

    def test_retry_config_accepted(self):
        data = {"name": "a", "intent": "i", "retry": {"max_attempts": 3}}
        config = ActionConfig.model_validate(data)
        assert config.retry.max_attempts == 3

    @pytest.mark.parametrize(
        ("extra", "match"),
        [
            pytest.param({"totally_bogus": True}, "totally_bogus", id="bogus_key"),
            # use model_vendor/model_name instead
            pytest.param({"vendor": "anthropic"}, "vendor", id="vendor_shorthand"),
            # only the _version_context alias is accepted from user input
            pytest.param(
                {"version_context": {"key": "val"}},
                "version_context",
                id="version_context_by_name",
            ),
            # ambiguous: retry must be a mapping
            pytest.param({"retry": True}, "retry", id="retry_true"),
            pytest.param({"temperature": "banana"}, "temperature", id="temperature_str"),
            pytest.param({"max_tokens": "lots"}, "max_tokens", id="max_tokens_str"),
            pytest.param(
                {"on_schema_mismatch": "reject"}, "on_schema_mismatch", id="on_schema_mismatch"
            ),
            pytest.param({"strict_schema": True}, "strict_schema", id="strict_schema"),
            pytest.param({"is_operational": "maybe"}, "is_operational", id="is_operational_str"),
            pytest.param({"chunk_size": "big"}, "chunk_size", id="chunk_size_str"),
            pytest.param({"run_mode": "invalid"}, "run_mode", id="run_mode_invalid"),
            pytest.param({"run_mode": "realtime"}, "run_mode", id="run_mode_realtime"),
            # old spelling of skip_condition
            pytest.param({"skip_if": "x > 1"}, "skip_if", id="skip_if"),
            # old spelling of dependencies
            pytest.param({"depends_on": ["other"]}, "depends_on", id="depends_on"),
        ],
    )
    def test_invalid_key_or_value_rejected(self, extra, match):
        with pytest.raises(ValidationError, match=match):
            ActionConfig.model_validate({"name": "a", "intent": "i", **extra})

    def test_intent_required(self):
        with pytest.raises(ValidationError, match="intent"):
            ActionConfig.model_validate({"name": "a"})

    def test_run_mode_none_accepted(self):
        """RunMode: None must be accepted (optional field)."""
        data = {"name": "a", "intent": "i"}
        config = ActionConfig.model_validate(data)
        assert config.run_mode is None

    # --- Version config ---

    def test_versions_without_param_defaults_to_i(self):
        """Shipped workflows omit param; runtime defaults to 'i'."""
        data = {
            "name": "a",
            "intent": "i",
            "versions": {"range": [1, 3]},
        }
        config = ActionConfig.model_validate(data)
        assert config.versions.param == "i"
        assert config.versions.range == [1, 3]

    def test_versions_with_explicit_param(self):
        data = {
            "name": "a",
            "intent": "i",
            "versions": {"param": "classifier_id", "range": [1, 5]},
        }
        config = ActionConfig.model_validate(data)
        assert config.versions.param == "classifier_id"

    def test_version_consumption_match_pattern(self):
        """pattern: match is used by shipped workflows."""
        data = {
            "name": "a",
            "intent": "i",
            "version_consumption": {"source": "train_model", "pattern": "match"},
        }
        config = ActionConfig.model_validate(data)
        assert config.version_consumption.pattern.value == "match"

    def test_version_consumption_merge_pattern(self):
        data = {
            "name": "a",
            "intent": "i",
            "version_consumption": {"source": "evaluate_model", "pattern": "merge"},
        }
        config = ActionConfig.model_validate(data)
        assert config.version_consumption.pattern.value == "merge"


class TestDefaultsConfigValidation:
    """DefaultsConfig with extra='forbid' refuses a key it does not declare."""

    def test_unknown_key_refused(self):
        data = {"model_vendor": "openai", "totally_bogus": True}
        with pytest.raises(ValidationError) as excinfo:
            DefaultsConfig.model_validate(data)

        # not `match=`: that reads str(ValidationError), which echoes the input
        assert "unknown defaults key 'totally_bogus'" in excinfo.value.errors()[0]["msg"]

    def test_provider_specific_params_accepted(self):
        """frequency_penalty, presence_penalty are valid vendor-specific defaults."""
        data = {
            "model_vendor": "openai",
            "temperature": 0.7,
            "frequency_penalty": 0.2,
            "presence_penalty": 0.1,
        }
        config = DefaultsConfig.model_validate(data)
        assert config.model_vendor == "openai"
        assert config.temperature == 0.7
        assert config.frequency_penalty == 0.2
        assert config.presence_penalty == 0.1

    def test_empty_defaults_accepted(self):
        config = DefaultsConfig.model_validate({})
        assert config.model_vendor is None

    def test_temperature_rejects_non_numeric(self):
        with pytest.raises(ValidationError, match="temperature"):
            DefaultsConfig.model_validate({"temperature": "warm"})

    def test_retry_false_converts_to_none(self):
        config = DefaultsConfig.model_validate({"retry": False})
        assert config.retry is None

    def test_retry_true_rejected(self):
        with pytest.raises(ValidationError, match="retry"):
            DefaultsConfig.model_validate({"retry": True})


@pytest.mark.parametrize(
    ("model", "field", "raw", "expected"),
    [
        pytest.param(ActionConfig, "granularity", "Record", "record", id="action_granularity"),
        pytest.param(ActionConfig, "run_mode", "BATCH", "batch", id="action_run_mode"),
        pytest.param(ActionConfig, "kind", "LLM", "llm", id="action_kind"),
        pytest.param(DefaultsConfig, "granularity", "Record", "record", id="defaults_granularity"),
        pytest.param(DefaultsConfig, "run_mode", "Batch", "batch", id="defaults_run_mode"),
    ],
)
def test_mixed_case_enum_value_accepted_and_normalized(model, field, raw, expected):
    data = {"name": "a", "intent": "i"} if model is ActionConfig else {}
    config = model.model_validate({**data, field: raw})
    assert getattr(config, field).value == expected
