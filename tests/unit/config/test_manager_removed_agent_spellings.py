"""Regression tests for ConfigManager.merge_agent_configs() refusing removed
legacy field spellings (607).

The legacy top-level `agents:` config format bypasses ActionConfig entirely
and validates raw dicts via AgentConfig (extra="allow"), so a removed
spelling would otherwise pass through untouched and be silently misread by
every downstream consumer that no longer has a fallback for it — not
refused, and not honored either.
"""

import pytest

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
