"""`google` is `gemini` by the time an agent's config is merged, on every route.

An `agents:` block never passes the expander, and a project's `default_agent_config:`
is laid under each agent at merge, so `AgentConfig` is where those routes meet the
actions format. The merged config is what later readers take the vendor from, so it
holds one name whatever route the agent came by.
"""

from agent_actions.config.manager import ConfigManager
from agent_actions.llm.config.vendor import api_key_env_var
from agent_actions.output.response.config_schema import AgentConfig


def _manager(default_agent_config: dict | None = None) -> ConfigManager:
    manager = ConfigManager.__new__(ConfigManager)
    manager.default_config = (
        {"default_agent_config": default_agent_config} if default_agent_config else {}
    )
    manager.tool_path = None
    manager.agent_configs = {}
    return manager


class TestAnAgentThatWritesGoogle:
    def test_the_agent_model_holds_gemini(self):
        agent = AgentConfig.model_validate({"agent_type": "a1", "model_vendor": "google"})

        assert agent.model_vendor == "gemini"

    def test_an_agents_block_entry_is_merged_as_gemini(self):
        manager = _manager()

        manager.merge_agent_configs(
            [{"agent_type": "a1", "model_vendor": "google", "model_name": "m", "chunk_config": {}}]
        )

        assert manager.agent_configs["a1"].model_vendor == "gemini"

    def test_the_project_default_is_merged_under_an_agent_as_gemini(self):
        manager = _manager({"model_vendor": "google", "model_name": "m", "api_key": "K"})

        manager.merge_agent_configs([{"agent_type": "a1", "chunk_config": {}}])

        assert manager.agent_configs["a1"].model_vendor == "gemini"

    def test_the_key_preflight_asks_for_is_the_gemini_one(self):
        manager = _manager()
        manager.merge_agent_configs(
            [{"agent_type": "a1", "model_vendor": "google", "model_name": "m", "chunk_config": {}}]
        )

        vendor = manager.agent_configs["a1"].model_vendor

        assert vendor == "gemini"
        assert api_key_env_var(vendor) == "GEMINI_API_KEY"


class TestWhatTheAliasDoesNotTouch:
    def test_a_vendor_that_is_not_an_alias_is_left_as_written(self):
        assert (
            AgentConfig.model_validate({"agent_type": "a1", "model_vendor": "openai"}).model_vendor
            == "openai"
        )
        assert (
            AgentConfig.model_validate(
                {"agent_type": "a1", "model_vendor": "nonesuch"}
            ).model_vendor
            == "nonesuch"
        )

    def test_no_vendor_stays_none(self):
        assert AgentConfig.model_validate({"agent_type": "a1"}).model_vendor is None
