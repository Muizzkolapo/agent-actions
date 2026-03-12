"""Tests for HITL routing and expansion semantics."""

import pytest

from agent_actions.output.response.config_schema import AgentConfig
from agent_actions.output.response.expander import ActionExpander


def test_expand_actions_to_agents_allows_hitl_without_llm_required_fields():
    """HITL actions should expand without requiring model/api-key fields."""
    workflow = {
        "name": "hitl_workflow",
        "actions": [
            {
                "name": "review_data",
                "kind": "hitl",
                "intent": "Human review step",
                "hitl": {"instructions": "Review data"},
            }
        ],
    }

    expanded = ActionExpander.expand_actions_to_agents(workflow)
    agent = expanded["hitl_workflow"][0]

    assert agent["agent_type"] == "review_data"
    assert agent["model_vendor"] == "hitl"
    assert agent["hitl"]["instructions"] == "Review data"


def test_get_all_agent_configs_forces_kind_vendor_mapping():
    """kind=tool/hitl should override inherited/default model_vendor values."""
    # Import order avoids circular import between workflow.coordinator and ConfigManager.
    # Trigger coordinator import first to avoid circular import with ConfigManager.
    import agent_actions.workflow.coordinator  # noqa: F401
    from agent_actions.llm.realtime.config import ConfigManager

    manager = ConfigManager(constructor_path="unused.yml", default_path="")
    manager.agent_configs = {
        "review_data": AgentConfig.model_validate(
            {
                "agent_type": "review_data",
                "name": "review_data",
                "kind": "hitl",
                "model_vendor": "openai",
            }
        ),
        "transform_data": AgentConfig.model_validate(
            {
                "agent_type": "transform_data",
                "name": "transform_data",
                "kind": "tool",
                "model_vendor": "anthropic",
            }
        ),
    }

    normalized = manager.get_all_agent_configs_as_dicts()

    assert normalized["review_data"]["model_vendor"] == "hitl"
    assert normalized["transform_data"]["model_vendor"] == "tool"


def test_get_all_agent_configs_raises_on_none_model_vendor():
    """LLM actions with model_vendor=None should raise ConfigurationError."""
    # Trigger coordinator import first to avoid circular import with ConfigManager.
    import agent_actions.workflow.coordinator  # noqa: F401
    from agent_actions.errors import ConfigurationError
    from agent_actions.llm.realtime.config import ConfigManager

    manager = ConfigManager(constructor_path="unused.yml", default_path="")
    manager.agent_configs = {
        "classify": AgentConfig.model_validate(
            {
                "agent_type": "classify",
                "name": "classify",
                "kind": "llm",
                "model_vendor": None,
            }
        ),
    }

    with pytest.raises(ConfigurationError, match="missing required field 'model_vendor'"):
        manager.get_all_agent_configs_as_dicts()


def test_get_all_agent_configs_allows_none_vendor_for_tool_and_hitl():
    """tool/hitl actions should not raise even when model_vendor is None."""
    # Trigger coordinator import first to avoid circular import with ConfigManager.
    import agent_actions.workflow.coordinator  # noqa: F401
    from agent_actions.llm.realtime.config import ConfigManager

    manager = ConfigManager(constructor_path="unused.yml", default_path="")
    manager.agent_configs = {
        "review": AgentConfig.model_validate(
            {"agent_type": "review", "name": "review", "kind": "hitl"}
        ),
        "transform": AgentConfig.model_validate(
            {"agent_type": "transform", "name": "transform", "kind": "tool"}
        ),
    }

    result = manager.get_all_agent_configs_as_dicts()
    assert result["review"]["model_vendor"] == "hitl"
    assert result["transform"]["model_vendor"] == "tool"


def test_get_all_agent_configs_raises_on_empty_string_model_vendor():
    """LLM actions with model_vendor='' should also raise ConfigurationError."""
    # Trigger coordinator import first to avoid circular import with ConfigManager.
    import agent_actions.workflow.coordinator  # noqa: F401
    from agent_actions.errors import ConfigurationError
    from agent_actions.llm.realtime.config import ConfigManager

    manager = ConfigManager(constructor_path="unused.yml", default_path="")
    manager.agent_configs = {
        "classify": AgentConfig.model_validate(
            {
                "agent_type": "classify",
                "name": "classify",
                "kind": "llm",
                "model_vendor": "",
            }
        ),
    }

    with pytest.raises(ConfigurationError, match="missing required field 'model_vendor'"):
        manager.get_all_agent_configs_as_dicts()


def test_get_all_agent_configs_raises_when_kind_is_none():
    """Actions with kind=None (absent/unset) should still validate model_vendor."""
    # Trigger coordinator import first to avoid circular import with ConfigManager.
    import agent_actions.workflow.coordinator  # noqa: F401
    from agent_actions.errors import ConfigurationError
    from agent_actions.llm.realtime.config import ConfigManager

    manager = ConfigManager(constructor_path="unused.yml", default_path="")
    manager.agent_configs = {
        "summarize": AgentConfig.model_validate(
            {
                "agent_type": "summarize",
                "name": "summarize",
                "kind": None,
                "model_vendor": None,
            }
        ),
    }

    with pytest.raises(ConfigurationError, match="missing required field 'model_vendor'"):
        manager.get_all_agent_configs_as_dicts()
