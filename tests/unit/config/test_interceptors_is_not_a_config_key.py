"""`interceptors:` is not a config key — the system it configured was deleted.

Pinned on the declaration, the expander's copy, and the two agent models that
allow extras, because any one left open still loses the value in silence. The
copy is the worst of them: the value reaches the agent config, so a reader
dumping it sees the block present and apparently applied.
"""

import pytest
import yaml
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import WorkflowConfig
from agent_actions.errors import ConfigurationError
from agent_actions.output.response.expander import ActionExpander

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}

# The shape the deleted runtime took, so the probe is refused for being the key
# it is rather than for being malformed.
BLOCK = [{"type": "validation", "name": "schema_check"}]


def _workflow(defaults=None, action=None):
    return {
        "name": "wf",
        "description": "d",
        "version": "1.0",
        "defaults": {**BASE_DEFAULTS, **(defaults or {})},
        "actions": [{"name": "a1", "intent": "i", "prompt": "p", **(action or {})}],
    }


def _expand(action):
    """Expand a raw action dict, skipping validation.

    Deliberately not through `WorkflowConfig`: the schema now refuses this input,
    and a test that could only reach the expander through the schema would stop
    exercising it at exactly the point the expander's own half needs proving.
    """
    expanded = ActionExpander.expand_actions_to_agents(
        {
            "name": "wf",
            "actions": [{"name": "a1", "intent": "i", "prompt": "p", **action}],
            "defaults": dict(BASE_DEFAULTS),
        }
    )
    return expanded["wf"][0]


@pytest.mark.parametrize("level", ["action", "defaults"])
def test_a_workflow_carrying_interceptors_is_refused_at_load(level):
    """A workflow naming a retired key fails, rather than loading and doing nothing."""
    written = {"interceptors": BLOCK}
    config = _workflow(action=written) if level == "action" else _workflow(defaults=written)

    with pytest.raises(ValidationError) as caught:
        WorkflowConfig.model_validate(config)

    assert "interceptors" in str(caught.value)


def test_the_expander_hands_no_interceptors_to_the_agent():
    """The copy is what made the dead key look live, so its absence is asserted
    on the agent the expander actually built."""
    agent = _expand({"interceptors": BLOCK})

    assert "interceptors" not in agent, (
        f"the expander copied a key no stage reads onto the agent: {agent.get('interceptors')!r}"
    )


def test_the_expander_still_carries_the_key_it_processes_beside_interceptors():
    """Guard on the guard: the assertion above also passes if the expander stopped
    building agents, or ignored the action it was handed. The `version_consumption`
    copy sat in the same step and must survive — asserted on one agent built from
    an action carrying both."""
    agent = _expand(
        {"interceptors": BLOCK, "version_consumption": {"source": "gen", "pattern": "merge"}}
    )

    assert agent["version_consumption_config"] == {"source": "gen", "pattern": "merge"}
    assert "interceptors" not in agent


def test_the_legacy_agents_block_refuses_interceptors_too():
    """`agents:` configs validate against a model that allows extras, so dropping
    the declaration refuses nothing here — the key would still be carried onto the
    agent, which is the silence it was removed for."""
    manager = ConfigManager.__new__(ConfigManager)
    manager.default_config = {}
    manager.tool_path = None
    manager.agent_configs = {}

    with pytest.raises(ConfigurationError) as caught:
        manager.merge_agent_configs(
            [{"agent_type": "a1", **BASE_DEFAULTS, "chunk_config": {}, "interceptors": BLOCK}]
        )

    assert "interceptors" in str(caught.value)


def test_the_project_files_agent_defaults_refuse_interceptors_too(tmp_path):
    """`default_agent_config:` is merged into every agent and validated against a
    model that allows extras, so a block written there reached all of them at once
    and was read by none."""
    (tmp_path / "agent_actions.yml").write_text(
        yaml.safe_dump(
            {
                "project_name": "p",
                "default_agent_config": {**BASE_DEFAULTS, "interceptors": BLOCK},
            }
        )
    )
    config_dir = tmp_path / "agent_config"
    config_dir.mkdir()
    # Named for the workflow it holds: the loader refuses a mismatch, which would
    # fail this test before it reached the refusal it is here to prove.
    (config_dir / "wf.yml").write_text(yaml.safe_dump(_workflow()))
    manager = ConfigManager(
        str(config_dir / "wf.yml"), str(tmp_path / "agent_actions.yml"), project_root=tmp_path
    )
    manager.load_configs()
    manager.validate_agent_name()

    with pytest.raises(ConfigurationError) as caught:
        manager.merge_agent_configs(manager.get_user_agents())

    assert "interceptors" in str(caught.value)
