"""Tests for HITL configuration validation."""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, ActionKind, HitlConfig


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
    with pytest.raises(ValidationError, match="HITL actions require 'hitl' configuration"):
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
