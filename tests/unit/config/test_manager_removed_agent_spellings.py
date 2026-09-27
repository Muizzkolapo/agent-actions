"""Regression tests for ConfigManager.merge_agent_configs() refusing removed
legacy field spellings (607).

The legacy top-level `agents:` config format bypasses ActionConfig entirely
and validates raw dicts via AgentConfig (extra="allow"), so a removed
spelling would otherwise pass through untouched and be silently misread by
every downstream consumer that no longer has a fallback for it — not
refused, and not honored either.
"""

import pytest
import yaml

from agent_actions.config.manager import ConfigManager
from agent_actions.errors import ConfigurationError


def _bare_manager() -> ConfigManager:
    """A ConfigManager with just enough state for merge_agent_configs()."""
    cm = ConfigManager.__new__(ConfigManager)
    cm.default_config = {}
    cm.tool_path = None
    cm.agent_configs = {}
    return cm


class TestMergeAgentConfigsRefusesRemovedSpellings:
    def test_depends_on_refused_not_silently_misread(self):
        cm = _bare_manager()
        user_agents = [
            {
                "agent_type": "consumer",
                "model_vendor": "openai",
                "model_name": "gpt-4",
                "depends_on": ["producer"],
            }
        ]
        with pytest.raises(ConfigurationError, match="removed field spelling"):
            cm.merge_agent_configs(user_agents)

    def test_skip_if_refused_not_silently_ignored(self):
        cm = _bare_manager()
        user_agents = [
            {
                "agent_type": "consumer",
                "model_vendor": "openai",
                "model_name": "gpt-4",
                "skip_if": "1 == 2",
            }
        ]
        with pytest.raises(ConfigurationError, match="removed field spelling"):
            cm.merge_agent_configs(user_agents)

    def test_error_names_the_replacement_field(self):
        cm = _bare_manager()
        user_agents = [{"agent_type": "consumer", "depends_on": ["producer"]}]

        with pytest.raises(ConfigurationError) as excinfo:
            cm.merge_agent_configs(user_agents)

        assert excinfo.value.context["replacements"] == {"depends_on": "dependencies"}

    def test_canonical_spelling_alone_is_accepted(self):
        """Sanity check: dependencies (the real field) is not caught by the guard."""
        cm = _bare_manager()
        user_agents = [
            {
                "agent_type": "consumer",
                "model_vendor": "openai",
                "model_name": "gpt-4",
                "dependencies": ["producer"],
                "chunk_config": {},
            }
        ]
        cm.merge_agent_configs(user_agents)
        assert "consumer" in cm.agent_configs
        assert cm.agent_configs["consumer"].dependencies == ["producer"]


class TestDefaultAgentConfigRefusesRemovedSpellings:
    """The project block is merged into every agent, so a removed spelling there
    is an escape hatch from the per-agent refusal above, not merely a gap (1065).

    A user who hits the per-agent error and does not know the replacement hoists
    the key into `default_agent_config:` to apply it everywhere; the error then
    disappears and the setting stops working across every agent at once.
    """

    def test_depends_on_in_project_block_refused(self):
        cm = _bare_manager()
        cm.default_config = {"default_agent_config": {"depends_on": ["ghost"]}}

        with pytest.raises(ConfigurationError, match="removed field spelling"):
            cm.merge_agent_configs([{"agent_type": "consumer", "chunk_config": {}}])

    def test_skip_if_in_project_block_refused(self):
        cm = _bare_manager()
        cm.default_config = {"default_agent_config": {"skip_if": "1 == 1"}}

        with pytest.raises(ConfigurationError, match="removed field spelling"):
            cm.merge_agent_configs([{"agent_type": "consumer", "chunk_config": {}}])

    def test_error_names_the_replacement_and_the_surface(self):
        """`default_agent_config:` lives in a different file from the workflow, so
        an error that does not name the surface sends the reader to the wrong one."""
        cm = _bare_manager()
        cm.default_config = {"default_agent_config": {"depends_on": ["ghost"], "skip_if": "1 == 1"}}

        with pytest.raises(ConfigurationError) as excinfo:
            cm.merge_agent_configs([{"agent_type": "consumer", "chunk_config": {}}])

        assert excinfo.value.context["replacements"] == {
            "depends_on": "dependencies",
            "skip_if": "skip_condition",
        }
        assert "default_agent_config" in str(excinfo.value)

    def test_canonical_spellings_in_project_block_still_accepted(self):
        """Guard against over-refusal: the real fields are not caught by the check."""
        cm = _bare_manager()
        cm.default_config = {
            "default_agent_config": {
                "dependencies": ["producer"],
                "skip_condition": {"condition_type": "previous_outputs_empty"},
            }
        }

        cm.merge_agent_configs([{"agent_type": "consumer", "chunk_config": {}}])

        merged = cm.agent_configs["consumer"]
        assert merged.dependencies == ["producer"]
        assert merged.skip_condition is not None

    def test_real_load_path_refuses_hoisted_spelling(self, tmp_path):
        """Through the whole path the issue reports: load_configs -> validate_agent_name
        -> get_user_agents -> merge_agent_configs. The narrow unit seam above can pass
        while the real path still accepts the key, so this asserts on the real one."""
        (tmp_path / "agent_actions.yml").write_text(
            yaml.safe_dump(
                {
                    "project_name": "p",
                    "default_agent_config": {
                        "model_vendor": "openai",
                        "model_name": "gpt-4",
                        "api_key": "k",
                        "depends_on": ["ghost"],
                    },
                }
            )
        )
        config_dir = tmp_path / "agent_config"
        config_dir.mkdir()
        (config_dir / "w.yml").write_text(
            yaml.safe_dump(
                {
                    "name": "w",
                    "description": "d",
                    "version": "1.0",
                    "defaults": {"model_vendor": "openai"},
                    "actions": [{"name": "a1", "intent": "i", "prompt": "p"}],
                }
            )
        )
        manager = ConfigManager(
            str(config_dir / "w.yml"),
            str(tmp_path / "agent_actions.yml"),
            project_root=tmp_path,
        )
        manager.load_configs()
        manager.validate_agent_name()

        with pytest.raises(ConfigurationError, match="removed field spelling"):
            manager.merge_agent_configs(manager.get_user_agents())
