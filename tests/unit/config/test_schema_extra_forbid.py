"""Tests for extra='forbid' on ActionConfig and DefaultsConfig.

Validates that Pydantic natively rejects unknown keys, accepts all valid
action-level and defaults-level keys, enforces proper types, and handles
Union types correctly.
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, DefaultsConfig
from agent_actions.config.types import RunMode


class TestActionConfigForbidsUnknownKeys:
    """ActionConfig with extra='forbid' rejects unrecognized keys."""

    def test_unknown_key_raises_validation_error(self):
        data = {"name": "test", "intent": "test", "totally_bogus": True}
        with pytest.raises(ValidationError, match="totally_bogus"):
            ActionConfig.model_validate(data)

    def test_accepts_all_valid_action_keys(self):
        """Comprehensive dict covering every ActionConfig field."""
        data = {
            "name": "full_action",
            "intent": "Test every field",
            "kind": "llm",
            "impl": None,
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {"type": "object"},
            "drops": ["field_a"],
            "observe": ["field_b"],
            "granularity": "record",
            "guard": "len(items) > 0",
            "policy": "default",
            "versions": None,
            "version_consumption": None,
            "retry": {"max_attempts": 3},
            "reprompt": {"validation": "check_fn"},
            "strict_schema": True,
            "on_schema_mismatch": "reject",
            "idempotency_key": "key-{id}",
            "prompt": "Do something",
            "dependencies": ["dep_a"],
            "primary_dependency": "dep_a",
            "reduce_key": "group_id",
            "hitl": None,
            "on_empty": "warn",
            # SIMPLE_CONFIG_FIELDS
            "api_key": "sk-xxx",
            "base_url": "http://localhost",
            "run_mode": "online",
            "is_operational": True,
            "json_mode": True,
            "prompt_debug": False,
            "output_field": "raw_response",
            "temperature": 0.7,
            "max_tokens": 1000,
            "top_p": 0.9,
            "stop": ["\n"],
            "constraints": [],
            # Runtime-consumed (from AgentConfig)
            "where_clause": {"clause": "status = 'active'"},
            "ephemeral": True,
            "anthropic_version": "2023-06-01",
            "enable_prompt_caching": True,
            "max_execution_time": 600,
            "enable_caching": True,
            # Expander-consumed
            "interceptors": [{"name": "log"}],
            "chunk_config": {"size": 100},
            "chunk_size": 100,
            "chunk_overlap": 10,
            "context_scope": {"input": "seed_data"},
            "version_mode": "parallel",
            "child": ["child_pipeline"],
            # Internal
            "_version_context": {"v1": "ctx"},
        }
        config = ActionConfig.model_validate(data)
        assert config.name == "full_action"
        assert config.version_context == {"v1": "ctx"}

    def test_version_context_accepted_via_alias(self):
        data = {"name": "a", "intent": "i", "_version_context": {"key": "val"}}
        config = ActionConfig.model_validate(data)
        assert config.version_context == {"key": "val"}

    def test_vendor_model_shorthand_rejected(self):
        """Old vendor/model shorthand rejected; use model_vendor/model_name."""
        data = {"name": "a", "intent": "i", "vendor": "anthropic"}
        with pytest.raises(ValidationError, match="vendor"):
            ActionConfig.model_validate(data)

    def test_version_context_by_field_name_rejected(self):
        """version_context (without underscore) must not be accepted from user input."""
        data = {"name": "a", "intent": "i", "version_context": {"key": "val"}}
        with pytest.raises(ValidationError, match="version_context"):
            ActionConfig.model_validate(data)

    # --- retry / reprompt mapping validation ---

    def test_reprompt_false_converts_to_none(self):
        """reprompt: false (disabled) is accepted and converted to None."""
        data = {"name": "a", "intent": "i", "reprompt": False}
        config = ActionConfig.model_validate(data)
        assert config.reprompt is None

    def test_reprompt_true_rejected(self):
        """reprompt: true is ambiguous and rejected (must use mapping)."""
        data = {"name": "a", "intent": "i", "reprompt": True}
        with pytest.raises(ValidationError, match="reprompt"):
            ActionConfig.model_validate(data)

    def test_reprompt_config_accepted(self):
        data = {"name": "a", "intent": "i", "reprompt": {"validation": "check"}}
        config = ActionConfig.model_validate(data)
        assert config.reprompt.validation == "check"

    def test_reprompt_without_validation_accepted(self):
        """Reprompt without validation (used with on_schema_mismatch: reprompt)."""
        data = {"name": "a", "intent": "i", "reprompt": {"max_attempts": 3}}
        config = ActionConfig.model_validate(data)
        assert config.reprompt.max_attempts == 3

    def test_retry_false_converts_to_none(self):
        """retry: false (disabled) is accepted and converted to None."""
        data = {"name": "a", "intent": "i", "retry": False}
        config = ActionConfig.model_validate(data)
        assert config.retry is None

    def test_retry_true_rejected(self):
        """retry: true is ambiguous and rejected (must use mapping)."""
        data = {"name": "a", "intent": "i", "retry": True}
        with pytest.raises(ValidationError, match="retry"):
            ActionConfig.model_validate(data)

    def test_retry_config_accepted(self):
        data = {"name": "a", "intent": "i", "retry": {"max_attempts": 3}}
        config = ActionConfig.model_validate(data)
        assert config.retry.max_attempts == 3

    # --- Type enforcement ---

    def test_temperature_rejects_non_numeric(self):
        data = {"name": "a", "intent": "i", "temperature": "banana"}
        with pytest.raises(ValidationError, match="temperature"):
            ActionConfig.model_validate(data)

    def test_max_tokens_rejects_non_int(self):
        data = {"name": "a", "intent": "i", "max_tokens": "lots"}
        with pytest.raises(ValidationError, match="max_tokens"):
            ActionConfig.model_validate(data)

    def test_on_schema_mismatch_rejects_invalid_value(self):
        data = {"name": "a", "intent": "i", "on_schema_mismatch": "ignore"}
        with pytest.raises(ValidationError, match="on_schema_mismatch"):
            ActionConfig.model_validate(data)

    def test_strict_schema_rejects_non_bool(self):
        data = {"name": "a", "intent": "i", "strict_schema": "banana"}
        with pytest.raises(ValidationError, match="strict_schema"):
            ActionConfig.model_validate(data)

    def test_is_operational_rejects_non_bool(self):
        data = {"name": "a", "intent": "i", "is_operational": "maybe"}
        with pytest.raises(ValidationError, match="is_operational"):
            ActionConfig.model_validate(data)

    def test_chunk_size_rejects_non_int(self):
        data = {"name": "a", "intent": "i", "chunk_size": "big"}
        with pytest.raises(ValidationError, match="chunk_size"):
            ActionConfig.model_validate(data)

    # --- Other validations ---

    def test_intent_required(self):
        with pytest.raises(ValidationError, match="intent"):
            ActionConfig.model_validate({"name": "a"})

    def test_granularity_mixed_case_accepted(self):
        """Granularity: Record (mixed-case) must be accepted."""
        data = {"name": "a", "intent": "i", "granularity": "Record"}
        config = ActionConfig.model_validate(data)
        assert config.granularity.value == "record"

    def test_run_mode_mixed_case_accepted(self):
        """RunMode: BATCH (uppercase) must be accepted."""
        data = {"name": "a", "intent": "i", "run_mode": "BATCH"}
        config = ActionConfig.model_validate(data)
        assert config.run_mode == RunMode.BATCH
        assert config.run_mode.value == "batch"

    def test_run_mode_none_accepted(self):
        """RunMode: None must be accepted (optional field)."""
        data = {"name": "a", "intent": "i"}
        config = ActionConfig.model_validate(data)
        assert config.run_mode is None

    def test_run_mode_invalid_rejected(self):
        """RunMode: invalid value must be rejected."""
        data = {"name": "a", "intent": "i", "run_mode": "invalid"}
        with pytest.raises(ValidationError, match="run_mode"):
            ActionConfig.model_validate(data)

    def test_run_mode_realtime_rejected(self):
        """RunMode: 'realtime' is not a valid mode and must be rejected."""
        data = {"name": "a", "intent": "i", "run_mode": "realtime"}
        with pytest.raises(ValidationError, match="run_mode"):
            ActionConfig.model_validate(data)

    def test_kind_mixed_case_accepted(self):
        """kind: LLM (mixed-case) must be accepted."""
        data = {"name": "a", "intent": "i", "kind": "LLM"}
        config = ActionConfig.model_validate(data)
        assert config.kind.value == "llm"

    def test_strict_schema_and_on_schema_mismatch_accepted(self):
        data = {
            "name": "a",
            "intent": "i",
            "strict_schema": True,
            "on_schema_mismatch": "reject",
        }
        config = ActionConfig.model_validate(data)
        assert config.strict_schema is True
        assert config.on_schema_mismatch == "reject"

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
        assert config.versions.mode.value == "parallel"

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
    """DefaultsConfig with extra='ignore' validates known keys, ignores vendor-specific."""

    def test_unknown_key_silently_ignored(self):
        """Vendor-specific params like frequency_penalty are silently ignored."""
        data = {"model_vendor": "openai", "totally_bogus": True}
        config = DefaultsConfig.model_validate(data)
        assert config.model_vendor == "openai"

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

    def test_accepts_all_valid_defaults_keys(self):
        """Comprehensive dict covering every DefaultsConfig field."""
        data = {
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "json_mode": True,
            "granularity": "record",
            "run_mode": "online",
            "drops": ["field_a"],
            "observe": ["field_b"],
            "data_source": "local",
            "hitl_timeout": 60,
            # SIMPLE_CONFIG_FIELDS
            "api_key": "sk-xxx",
            "base_url": "http://localhost",
            "kind": "llm",
            "is_operational": True,
            "prompt_debug": False,
            "output_field": "raw_response",
            "temperature": 0.7,
            "max_tokens": 1000,
            "top_p": 0.9,
            "stop": ["\n"],
            "reprompt": False,
            "constraints": [],
            "retry": None,
            "strict_schema": False,
            "on_schema_mismatch": "warn",
            # Expander-consumed
            "context_scope": {"input": "seed_data"},
            "chunk_config": {"size": 100},
            "chunk_size": 100,
            "chunk_overlap": 10,
        }
        config = DefaultsConfig.model_validate(data)
        assert config.model_vendor == "openai"

    def test_empty_defaults_accepted(self):
        config = DefaultsConfig.model_validate({})
        assert config.model_vendor is None

    def test_granularity_mixed_case_accepted(self):
        """Granularity: Record (mixed-case) must be accepted in defaults."""
        config = DefaultsConfig.model_validate({"granularity": "Record"})
        assert config.granularity.value == "record"

    def test_run_mode_mixed_case_accepted(self):
        """RunMode: Batch (mixed-case) must be accepted in defaults."""
        config = DefaultsConfig.model_validate({"run_mode": "Batch"})
        assert config.run_mode == RunMode.BATCH

    def test_temperature_rejects_non_numeric(self):
        with pytest.raises(ValidationError, match="temperature"):
            DefaultsConfig.model_validate({"temperature": "warm"})

    def test_on_schema_mismatch_rejects_invalid_value(self):
        with pytest.raises(ValidationError, match="on_schema_mismatch"):
            DefaultsConfig.model_validate({"on_schema_mismatch": "ignore"})

    def test_retry_false_converts_to_none(self):
        config = DefaultsConfig.model_validate({"retry": False})
        assert config.retry is None

    def test_retry_true_rejected(self):
        with pytest.raises(ValidationError, match="retry"):
            DefaultsConfig.model_validate({"retry": True})

    def test_reprompt_false_converts_to_none(self):
        config = DefaultsConfig.model_validate({"reprompt": False})
        assert config.reprompt is None

    def test_reprompt_true_rejected(self):
        with pytest.raises(ValidationError, match="reprompt"):
            DefaultsConfig.model_validate({"reprompt": True})
