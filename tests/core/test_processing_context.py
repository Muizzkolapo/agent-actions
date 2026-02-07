"""Tests for ProcessingContext dataclass."""

import pytest

from agent_actions.processing.types import ProcessingContext, ProcessingMode


class TestProcessingContextRequired:
    """Test required fields for ProcessingContext."""

    def test_requires_agent_config(self):
        """ProcessingContext requires agent_config dict."""
        with pytest.raises(TypeError, match="agent_config"):
            ProcessingContext(agent_name="test")  # Missing agent_config

    def test_requires_agent_name(self):
        """ProcessingContext requires agent_name string."""
        with pytest.raises(TypeError, match="agent_name"):
            ProcessingContext(agent_config={})  # Missing agent_name


class TestProcessingContextDefaults:
    """Test default values for ProcessingContext fields."""

    @pytest.mark.parametrize(
        "field,expected",
        [
            pytest.param("mode", ProcessingMode.ONLINE, id="mode"),
            pytest.param("is_first_stage", False, id="is_first_stage"),
            pytest.param("source_data", [], id="source_data"),
            pytest.param("record_index", 0, id="record_index"),
        ],
    )
    def test_defaults(self, field, expected):
        ctx = ProcessingContext(agent_config={}, agent_name="test")
        assert getattr(ctx, field) == expected


class TestProcessingContextProperties:
    """Test ProcessingContext properties."""

    def test_action_name_from_agent_type(self):
        """action_name returns agent_config['agent_type'] if present."""
        ctx = ProcessingContext(
            agent_config={"agent_type": "transform_action"}, agent_name="fallback_name"
        )

        assert ctx.action_name == "transform_action"

    def test_action_name_fallback_to_agent_name(self):
        """action_name returns agent_name if agent_type not in config."""
        ctx = ProcessingContext(agent_config={}, agent_name="fallback_name")

        assert ctx.action_name == "fallback_name"
