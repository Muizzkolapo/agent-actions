"""Tests for ProcessingContext dataclass."""

import pytest

from agent_actions.core.types import ProcessingContext, ProcessingMode


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

    def test_default_mode_is_online(self):
        """Default mode is ProcessingMode.ONLINE."""
        ctx = ProcessingContext(agent_config={}, agent_name="test")

        assert ctx.mode == ProcessingMode.ONLINE

    def test_default_is_first_stage_is_false(self):
        """Default is_first_stage is False (subsequent stage)."""
        ctx = ProcessingContext(agent_config={}, agent_name="test")

        assert ctx.is_first_stage is False

    def test_default_source_data_is_empty_list(self):
        """Default source_data is empty list."""
        ctx = ProcessingContext(agent_config={}, agent_name="test")

        assert ctx.source_data == []
        assert isinstance(ctx.source_data, list)

    def test_default_record_index_is_zero(self):
        """Default record_index is 0."""
        ctx = ProcessingContext(agent_config={}, agent_name="test")

        assert ctx.record_index == 0


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
