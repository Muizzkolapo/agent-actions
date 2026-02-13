"""Tests for HITL routing and expansion semantics."""

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
