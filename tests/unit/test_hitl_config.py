"""Tests for HITL configuration validation."""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, ActionKind, DefaultsConfig, HitlConfig
from agent_actions.errors import ConfigurationError
from agent_actions.output.response.expander import ActionExpander


def test_hitl_config_defaults():
    """Test HitlConfig default values."""
    config = HitlConfig(instructions="Review the data")

    assert config.port == 3001
    assert config.instructions == "Review the data"
    assert config.timeout == 300
    assert config.require_comment_on_reject is True


def test_hitl_config_custom_values():
    """Test HitlConfig with custom values."""
    config = HitlConfig(
        port=3002,
        instructions="Check this output",
        timeout=600,
        require_comment_on_reject=False,
    )

    assert config.port == 3002
    assert config.instructions == "Check this output"
    assert config.timeout == 600
    assert config.require_comment_on_reject is False


def test_hitl_config_port_validation():
    """Test port validation (must be 1024-65535)."""
    # Valid port
    config = HitlConfig(port=8080, instructions="Test")
    assert config.port == 8080

    # Port too low
    with pytest.raises(ValidationError):
        HitlConfig(port=80, instructions="Test")

    # Port too high
    with pytest.raises(ValidationError):
        HitlConfig(port=70000, instructions="Test")


def test_hitl_config_timeout_validation():
    """Test timeout validation (5-3600 seconds)."""
    # Valid timeout
    config = HitlConfig(instructions="Test", timeout=100)
    assert config.timeout == 100

    # Low but valid timeout (useful for testing)
    config_low = HitlConfig(instructions="Test", timeout=5)
    assert config_low.timeout == 5

    # Timeout too low
    with pytest.raises(ValidationError):
        HitlConfig(instructions="Test", timeout=4)

    # Timeout too high
    with pytest.raises(ValidationError):
        HitlConfig(instructions="Test", timeout=5000)


def test_hitl_config_instructions_required():
    """Test that instructions are required."""
    with pytest.raises(ValidationError):
        HitlConfig()

    # Empty string should fail
    with pytest.raises(ValidationError):
        HitlConfig(instructions="")


def test_action_config_with_hitl():
    """Test ActionConfig with HITL kind requires hitl config."""
    # Valid HITL action
    config = ActionConfig(
        name="review_data",
        intent="Human review",
        kind=ActionKind.HITL,
        hitl=HitlConfig(instructions="Review the output"),
    )

    assert config.kind == ActionKind.HITL
    assert config.hitl is not None
    assert config.hitl.instructions == "Review the output"


def test_action_config_hitl_missing_config():
    """Test that HITL action without hitl config raises error."""
    with pytest.raises(ValidationError, match="HITL action.*requires 'hitl' configuration"):
        ActionConfig(
            name="review_data",
            intent="Human review",
            kind=ActionKind.HITL,
            # Missing hitl config
        )


def test_action_config_non_hitl_with_hitl_config():
    """Test that non-HITL actions can have hitl config (it's just ignored)."""
    # This should be valid - hitl config is optional for non-HITL actions
    config = ActionConfig(
        name="process_data",
        intent="Process data",
        kind=ActionKind.LLM,
        hitl=HitlConfig(instructions="Test"),  # Present but not required
    )

    assert config.kind == ActionKind.LLM
    assert config.hitl is not None


def test_hitl_output_schema_constant_matches_server_fields():
    """Validate that HITL_OUTPUT_SCHEMA fields match _make_terminal_response output."""
    from agent_actions.utils.constants import HITL_OUTPUT_JSON_SCHEMA, HITL_OUTPUT_SCHEMA

    # The three core fields from _make_terminal_response in hitl/server.py
    expected_fields = {"hitl_status", "user_comment", "timestamp"}

    # Check unified schema fields
    schema_field_ids = {f["id"] for f in HITL_OUTPUT_SCHEMA["fields"]}
    assert schema_field_ids == expected_fields

    # Check JSON schema properties
    json_props = set(HITL_OUTPUT_JSON_SCHEMA["properties"].keys())
    assert json_props == expected_fields

    # Check required fields (user_comment is optional)
    assert set(HITL_OUTPUT_JSON_SCHEMA["required"]) == {"hitl_status", "timestamp"}

    # Verify additionalProperties is False (strict schema)
    assert HITL_OUTPUT_JSON_SCHEMA["additionalProperties"] is False


# -- Workflow-level hitl_timeout default tests --


def _expand_hitl(hitl_config, defaults=None):
    """Helper: expand a HITL action through the expander pipeline."""
    defaults = defaults or {}
    action = {
        "name": "review",
        "intent": "Human review",
        "kind": "hitl",
        "hitl": hitl_config,
    }
    agent = {"agent_type": "review", "name": "review"}
    return ActionExpander._create_agent_from_action(action, defaults, agent, lambda x: x)


def test_workflow_default_hitl_timeout_applied():
    """Workflow hitl_timeout flows through when action omits timeout."""
    result = _expand_hitl(
        {"instructions": "Review"},
        defaults={"hitl_timeout": 600},
    )
    assert result["hitl"]["timeout"] == 600


def test_action_timeout_overrides_workflow_default():
    """Action-level timeout takes precedence over workflow default."""
    result = _expand_hitl(
        {"instructions": "Review", "timeout": 120},
        defaults={"hitl_timeout": 600},
    )
    assert result["hitl"]["timeout"] == 120


def test_no_workflow_default_uses_hardcoded():
    """Without workflow default, action hitl dict has no timeout key (server uses 300s)."""
    result = _expand_hitl({"instructions": "Review"})
    # No timeout injected — downstream HitlConfig model defaults to 300
    assert "timeout" not in result["hitl"]


def test_defaults_config_hitl_timeout_validation():
    """DefaultsConfig.hitl_timeout respects 5–3600 range."""
    valid = DefaultsConfig(hitl_timeout=60)
    assert valid.hitl_timeout == 60

    with pytest.raises(ValidationError):
        DefaultsConfig(hitl_timeout=4)

    with pytest.raises(ValidationError):
        DefaultsConfig(hitl_timeout=3601)


def test_hitl_config_not_mutated_by_expansion():
    """Expanding HITL action must not mutate the source hitl config dict."""
    source_hitl = {"instructions": "Review"}
    _expand_hitl(source_hitl, defaults={"hitl_timeout": 600})
    # Source dict must remain unmodified
    assert "timeout" not in source_hitl


def test_hitl_timeout_default_rejects_non_numeric():
    """Runtime validation catches non-numeric hitl_timeout from raw YAML."""
    with pytest.raises(ConfigurationError, match="must be an integer between 5 and 3600"):
        _expand_hitl({"instructions": "Review"}, defaults={"hitl_timeout": "notanumber"})


def test_hitl_timeout_default_rejects_out_of_range():
    """Runtime validation catches out-of-range hitl_timeout from raw dict."""
    with pytest.raises(ConfigurationError):
        _expand_hitl({"instructions": "Review"}, defaults={"hitl_timeout": 2})

    with pytest.raises(ConfigurationError):
        _expand_hitl({"instructions": "Review"}, defaults={"hitl_timeout": 9999})


def test_hitl_timeout_default_rejects_float():
    """Fractional values are rejected instead of silently truncated."""
    with pytest.raises(ConfigurationError, match="must be an integer"):
        _expand_hitl({"instructions": "Review"}, defaults={"hitl_timeout": 5.9})
