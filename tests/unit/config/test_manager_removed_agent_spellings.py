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


_REMOVED = [
    pytest.param("depends_on", ["producer"], id="depends_on"),
]


class TestMergeAgentConfigsRefusesRemovedSpellings:
    @pytest.mark.parametrize(("key", "value"), _REMOVED)
    def test_removed_spelling_refused_not_silently_misread(self, key, value):
        cm = _bare_manager()
        user_agents = [
            {
                "agent_type": "consumer",
                "model_vendor": "openai",
                "model_name": "gpt-4",
                key: value,
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

    @pytest.mark.parametrize(("key", "value"), _REMOVED)
    def test_removed_spelling_in_project_block_refused(self, key, value):
        cm = _bare_manager()
        cm.default_config = {"default_agent_config": {key: value}}

        with pytest.raises(ConfigurationError, match="removed field spelling"):
            cm.merge_agent_configs([{"agent_type": "consumer", "chunk_config": {}}])

    def test_error_names_the_replacement_and_the_surface(self):
        """`default_agent_config:` lives in a different file from the workflow, so
        an error that does not name the surface sends the reader to the wrong one."""
        cm = _bare_manager()
        cm.default_config = {"default_agent_config": {"depends_on": ["ghost"]}}

        with pytest.raises(ConfigurationError) as excinfo:
            cm.merge_agent_configs([{"agent_type": "consumer", "chunk_config": {}}])

        assert excinfo.value.context["replacements"] == {"depends_on": "dependencies"}
        assert "default_agent_config" in str(excinfo.value)
