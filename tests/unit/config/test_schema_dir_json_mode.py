"""Tests for schema validation conditional on json_mode.

Non-JSON-mode workflows (json_mode: false in defaults, no action override)
should skip schema directory validation entirely.
"""

from __future__ import annotations

from agent_actions.prompt.renderer import ConfigRenderingService


class TestWorkflowNeedsSchema:
    """Unit tests for ConfigRenderingService._workflow_needs_schema."""

    def test_returns_true_when_json_mode_unset(self):
        """No json_mode in defaults → defaults to True at runtime."""
        config = {"defaults": {"model_name": "gpt-4"}, "actions": []}
        assert ConfigRenderingService._workflow_needs_schema(config) is True

    def test_returns_true_when_json_mode_true(self):
        """Explicit json_mode: true in defaults."""
        config = {"defaults": {"json_mode": True}, "actions": []}
        assert ConfigRenderingService._workflow_needs_schema(config) is True

    def test_returns_false_when_json_mode_false(self):
        """json_mode: false in defaults, no action overrides."""
        config = {"defaults": {"json_mode": False}, "actions": [{"name": "step1"}]}
        assert ConfigRenderingService._workflow_needs_schema(config) is False

    def test_returns_true_when_default_false_but_action_overrides(self):
        """json_mode: false in defaults but one action sets json_mode: true."""
        config = {
            "defaults": {"json_mode": False},
            "actions": [
                {"name": "step1"},
                {"name": "step2", "json_mode": True},
            ],
        }
        assert ConfigRenderingService._workflow_needs_schema(config) is True

    def test_returns_false_when_all_actions_also_false(self):
        """json_mode: false everywhere — no schema needed."""
        config = {
            "defaults": {"json_mode": False},
            "actions": [
                {"name": "step1", "json_mode": False},
                {"name": "step2"},
            ],
        }
        assert ConfigRenderingService._workflow_needs_schema(config) is False

    def test_returns_true_when_no_defaults_section(self):
        """No defaults section at all → json_mode defaults to True."""
        config = {"actions": [{"name": "step1"}]}
        assert ConfigRenderingService._workflow_needs_schema(config) is True

    def test_returns_true_when_defaults_is_none(self):
        """defaults: null in config."""
        config = {"defaults": None, "actions": []}
        assert ConfigRenderingService._workflow_needs_schema(config) is True
