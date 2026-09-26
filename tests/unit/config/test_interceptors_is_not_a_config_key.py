"""`interceptors:` is not a config key — the system it configured was deleted.

Every surface is asserted to give the reason, not just to fail: a user who reads
"unknown key" relocates the block, and relocating it is how the key reached every
agent unread to begin with. The expander's copy is the worst of the sites, since
the value arrives on the agent config and so looks applied to anyone dumping it.
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

# What the refusal has to say on every surface. Without this the message may
# degrade to a generic unknown-key error and the tests would not notice — and a
# generic error is what sends a user to move the block somewhere it still dies.
GUIDANCE = ("is no longer read", "configures nothing", "remove it")


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


def _bare_manager() -> ConfigManager:
    cm = ConfigManager.__new__(ConfigManager)
    cm.default_config = {}
    cm.tool_path = None
    cm.agent_configs = {}
    return cm


def _project(tmp_path, agent_defaults):
    """A project whose agent_actions.yml carries *agent_defaults*."""
    (tmp_path / "agent_actions.yml").write_text(
        yaml.safe_dump({"project_name": "p", "default_agent_config": agent_defaults})
    )
    config_dir = tmp_path / "agent_config"
    config_dir.mkdir()
    # Named for the workflow it holds: the loader refuses a mismatch, which would
    # fail these tests before they reached the refusal they are here to prove.
    (config_dir / "wf.yml").write_text(yaml.safe_dump(_workflow()))
    manager = ConfigManager(
        str(config_dir / "wf.yml"), str(tmp_path / "agent_actions.yml"), project_root=tmp_path
    )
    manager.load_configs()
    manager.validate_agent_name()
    return manager


def _assert_says_why(message, surface):
    for phrase in GUIDANCE:
        assert phrase in message, (
            f"the {surface} refusal does not say why, so it reads as a typo: {message!r}"
        )


@pytest.mark.parametrize("level", ["action", "defaults"])
def test_a_workflow_carrying_interceptors_is_refused_with_the_reason(level):
    """The strict surfaces. `defaults:` never declared the key, but a refusal that
    only lists valid keys sends the author to try another level."""
    written = {"interceptors": BLOCK}
    config = _workflow(action=written) if level == "action" else _workflow(defaults=written)

    with pytest.raises(ValidationError) as caught:
        WorkflowConfig.model_validate(config)

    message = str(caught.value)
    assert "interceptors" in message
    _assert_says_why(message, level)


def test_the_refusal_names_the_action_it_came_from():
    """pydantic locates the error as `actions.0`; a workflow of thirty needs the name."""
    with pytest.raises(ValidationError) as caught:
        WorkflowConfig.model_validate(
            _workflow(action={"name": "review_extraction", "interceptors": BLOCK})
        )

    assert "review_extraction" in str(caught.value).split("input_value")[0]


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
    manager = _bare_manager()

    with pytest.raises(ConfigurationError) as caught:
        manager.merge_agent_configs(
            [{"agent_type": "a1", **BASE_DEFAULTS, "chunk_config": {}, "interceptors": BLOCK}]
        )

    message = str(caught.value)
    assert "interceptors" in message
    _assert_says_why(message, "agent")
    assert "a1" in message, "a list of agents needs to say which one carried it"


def test_the_project_files_agent_defaults_refuse_interceptors_too(tmp_path):
    """`default_agent_config:` is merged into every agent and validated against a
    model that allows extras, so a block written there reached all of them at once
    and was read by none."""
    manager = _project(tmp_path, {**BASE_DEFAULTS, "interceptors": BLOCK})

    with pytest.raises(ConfigurationError) as caught:
        manager.merge_agent_configs(manager.get_user_agents())

    message = str(caught.value)
    assert "interceptors" in message
    _assert_says_why(message, "default_agent_config")


def test_a_clean_project_still_reaches_every_agent(tmp_path):
    """Control: the block really is merged into each agent, so the refusal above
    guards a value that arrived there — and the new check refuses nothing else.

    Asserted on a setting the workflow does not also carry, since one it does
    would be the action's own value arriving rather than the project's.
    """
    manager = _project(tmp_path, {**BASE_DEFAULTS, "temperature": 0.42})

    manager.merge_agent_configs(manager.get_user_agents())

    assert manager.agent_configs["a1"].model_dump()["temperature"] == 0.42


def test_a_clean_legacy_agent_still_merges():
    """Control for the other call site: a legacy entry naming nothing retired loads."""
    manager = _bare_manager()

    manager.merge_agent_configs([{"agent_type": "a1", **BASE_DEFAULTS, "chunk_config": {}}])

    assert manager.agent_configs["a1"].model_dump()["model_name"] == "gpt-4"
