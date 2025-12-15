"""Test that tool_path from root config is merged into agent configs."""

import pytest
from pathlib import Path
from agent_actions.llm_invocation.realtime.config_handler import ConfigManager


def test_tool_path_merged_into_agent_configs(tmp_path):
    """Test that root-level tool_path is merged into each agent's config."""

    # Create default config with tool_path at root level
    default_config_path = tmp_path / "agent_actions.yml"
    default_config_path.write_text("""
default_agent_config:
  model_name: gpt-4
  api_key: TEST_KEY
tool_path: ["tools"]
""")

    # Create user config with an agent
    user_config_path = tmp_path / "workflow.yml"
    user_config_path.write_text("""
name: test_workflow
actions:
  - name: test_agent
    agent_type: test_agent
    prompt: "Test prompt with dispatch_task('func')"
    model_vendor: openai
    schema: test_schema
""")

    # Load config
    config_manager = ConfigManager(
        default_path=str(default_config_path),
        user_path=str(user_config_path)
    )

    # Check that tool_path was loaded
    assert config_manager.tool_path == ["tools"], \
        f"Expected tool_path to be loaded, got {config_manager.tool_path}"

    # Check that tool_path was merged into agent config
    test_agent_config = config_manager.agent_configs.get('test_agent')
    assert test_agent_config is not None, "test_agent config not found"

    agent_dict = test_agent_config.model_dump()
    assert 'tool_path' in agent_dict, \
        f"tool_path not found in agent config. Keys: {list(agent_dict.keys())}"
    assert agent_dict['tool_path'] == ["tools"], \
        f"Expected tool_path=['tools'], got {agent_dict['tool_path']}"


def test_resolve_tools_path_from_merged_config(tmp_path):
    """Test that resolve_tools_path works with merged agent config."""
    from agent_actions.utilities.tools_resolver import resolve_tools_path

    # Simulate merged agent config with tool_path
    agent_config = {
        'agent_type': 'test_agent',
        'model_vendor': 'openai',
        'tool_path': ['tools'],  # Merged from root config
        'prompt': "Test with dispatch_task('func')"
    }

    resolved = resolve_tools_path(agent_config)
    assert resolved == 'tools', \
        f"Expected 'tools', got {resolved}"
