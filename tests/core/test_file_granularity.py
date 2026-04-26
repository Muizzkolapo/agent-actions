"""Tests for FILE granularity mode."""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.processing.record_processor import RecordProcessor


class TestFileGranularityValidation:
    """Test FILE granularity validation in RecordProcessor."""

    def test_file_granularity_allowed_for_kind_tool(self):
        """FILE granularity allowed when kind is 'tool'."""
        agent_config = {
            "granularity": "file",
            "kind": "tool",
        }

        # Should not raise
        processor = RecordProcessor(agent_config=agent_config, agent_name="test_tool")
        assert processor is not None

    def test_file_granularity_allowed_for_kind_hitl(self):
        """FILE granularity allowed when kind is 'hitl'."""
        agent_config = {
            "granularity": "file",
            "kind": "hitl",
        }

        # Should not raise
        processor = RecordProcessor(agent_config=agent_config, agent_name="test_hitl")
        assert processor is not None

    def test_file_granularity_blocked_for_kind_llm(self):
        """FILE granularity blocked when kind is 'llm'."""
        agent_config = {
            "granularity": "file",
            "kind": "llm",
            "model_vendor": "anthropic",
        }

        with pytest.raises(ConfigurationError) as exc_info:
            RecordProcessor(agent_config=agent_config, agent_name="test_llm")

        assert "FILE granularity is only supported for tool and hitl actions" in str(exc_info.value)

    def test_file_granularity_blocked_when_kind_not_set(self):
        """FILE granularity blocked when kind is not set (defaults to llm behavior)."""
        agent_config = {
            "granularity": "file",
            "model_vendor": "anthropic",
        }

        with pytest.raises(ConfigurationError) as exc_info:
            RecordProcessor(agent_config=agent_config, agent_name="test_no_kind")

        assert "FILE granularity is only supported for tool and hitl actions" in str(exc_info.value)

    def test_file_granularity_with_guard_allowed(self):
        """FILE granularity with guard is allowed (guards act as pre-filter)."""
        agent_config = {
            "granularity": "file",
            "kind": "tool",
            "guard": {"clause": "status == 'active'", "behavior": "skip"},
        }

        # Should not raise — guards are now handled as a pre-filter in FILE mode
        processor = RecordProcessor(agent_config=agent_config, agent_name="test_guard")
        assert processor is not None

    def test_record_granularity_with_guard_allowed(self):
        """RECORD granularity with guard is allowed."""
        agent_config = {
            "granularity": "record",
            "kind": "tool",
            "guard": {"clause": "status == 'active'", "behavior": "skip"},
        }

        # Should not raise
        processor = RecordProcessor(agent_config=agent_config, agent_name="test_guard_record")
        assert processor is not None

    def test_record_granularity_allowed_for_non_hitl_kinds(self):
        """RECORD granularity allowed for tool, llm, and unset kinds (not hitl)."""
        for kind in ["tool", "llm", ""]:
            agent_config = {
                "granularity": "record",
                "kind": kind,
            }

            # Should not raise
            processor = RecordProcessor(
                agent_config=agent_config, agent_name=f"test_{kind or 'empty'}"
            )
            assert processor is not None

    def test_hitl_record_granularity_blocked(self):
        """HITL actions with RECORD granularity are blocked."""
        agent_config = {
            "granularity": "record",
            "kind": "hitl",
        }

        with pytest.raises(ConfigurationError) as exc_info:
            RecordProcessor(agent_config=agent_config, agent_name="test_hitl_record")

        assert "HITL actions require FILE granularity" in str(exc_info.value)
