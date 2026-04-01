"""Tests for schema_dir validation conditional on json_mode.

Non-JSON-mode agents (json_mode: false in defaults, no action override)
should not require a schema directory to exist.
"""

from __future__ import annotations

import yaml

from agent_actions.config.project_paths import _peek_requires_json_mode


class TestPeekRequiresJsonMode:
    """Unit tests for _peek_requires_json_mode helper."""

    def test_returns_true_when_config_missing(self, tmp_path):
        """Missing config file → safe default: require schema."""
        assert _peek_requires_json_mode(tmp_path, "nonexistent") is True

    def test_returns_true_when_json_mode_unset(self, tmp_path):
        """No json_mode in defaults → defaults to True at runtime."""
        config = {"name": "test", "defaults": {"model_name": "gpt-4"}, "actions": []}
        (tmp_path / "test.yml").write_text(yaml.dump(config))
        assert _peek_requires_json_mode(tmp_path, "test") is True

    def test_returns_true_when_json_mode_true(self, tmp_path):
        """Explicit json_mode: true in defaults."""
        config = {"name": "test", "defaults": {"json_mode": True}, "actions": []}
        (tmp_path / "test.yml").write_text(yaml.dump(config))
        assert _peek_requires_json_mode(tmp_path, "test") is True

    def test_returns_false_when_json_mode_false(self, tmp_path):
        """json_mode: false in defaults, no action overrides."""
        config = {
            "name": "test",
            "defaults": {"json_mode": False},
            "actions": [{"name": "step1"}],
        }
        (tmp_path / "test.yml").write_text(yaml.dump(config))
        assert _peek_requires_json_mode(tmp_path, "test") is False

    def test_returns_true_when_default_false_but_action_overrides(self, tmp_path):
        """json_mode: false in defaults but one action sets json_mode: true."""
        config = {
            "name": "test",
            "defaults": {"json_mode": False},
            "actions": [
                {"name": "step1"},
                {"name": "step2", "json_mode": True},
            ],
        }
        (tmp_path / "test.yml").write_text(yaml.dump(config))
        assert _peek_requires_json_mode(tmp_path, "test") is True

    def test_returns_false_when_all_actions_also_false(self, tmp_path):
        """json_mode: false everywhere — no schema needed."""
        config = {
            "name": "test",
            "defaults": {"json_mode": False},
            "actions": [
                {"name": "step1", "json_mode": False},
                {"name": "step2"},
            ],
        }
        (tmp_path / "test.yml").write_text(yaml.dump(config))
        assert _peek_requires_json_mode(tmp_path, "test") is False

    def test_returns_true_when_no_defaults_section(self, tmp_path):
        """No defaults section at all → json_mode defaults to True."""
        config = {"name": "test", "actions": [{"name": "step1"}]}
        (tmp_path / "test.yml").write_text(yaml.dump(config))
        assert _peek_requires_json_mode(tmp_path, "test") is True

    def test_returns_true_on_malformed_yaml(self, tmp_path):
        """Malformed YAML → safe default: require schema."""
        (tmp_path / "test.yml").write_text(": : invalid yaml {{")
        assert _peek_requires_json_mode(tmp_path, "test") is True
