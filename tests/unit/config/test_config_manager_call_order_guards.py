"""ConfigManager raises RuntimeError, not AssertionError, when a method is called before load_configs."""

import pytest

from agent_actions.config.manager import ConfigManager


class TestConfigManagerSequencingGuards:
    """ConfigManager methods raise RuntimeError when called out of order."""

    def _make_manager(self, tmp_path):
        cfg = tmp_path / "test.yml"
        cfg.write_text("test:\n  - kind: llm\n")
        default = tmp_path / "default.yml"
        default.write_text("{}")
        return ConfigManager(str(cfg), str(default), project_root=tmp_path)

    def test_validate_agent_name_before_load(self, tmp_path):
        cm = self._make_manager(tmp_path)
        with pytest.raises(RuntimeError, match="load_configs.*must be called"):
            cm.validate_agent_name()

    def test_get_user_agents_before_load(self, tmp_path):
        cm = self._make_manager(tmp_path)
        with pytest.raises(RuntimeError, match="load_configs.*must be called"):
            cm.get_user_agents()
