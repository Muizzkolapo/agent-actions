"""`request_timeout` is set on an action, in `defaults:` or in `default_agent_config:`.

It reaches each agent the way `temperature` does, is refused at load unless it is a
positive number of seconds, and is not part of the config an action's answers are
stamped under: it bounds how long a request may take, not what the answer is.
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import ActionConfig, DefaultsConfig, WorkflowConfig
from agent_actions.errors import ConfigurationError
from agent_actions.output.response.config_schema import AgentConfig, DefaultAgentConfig
from agent_actions.output.response.expander import ActionExpander
from agent_actions.workflow.executor import _edits_since, config_in_force

BASE = {"model_vendor": "openai", "model_name": "gpt-4o-mini", "api_key": "KEY"}


def _agent(
    *, project: dict | None = None, defaults: dict | None = None, action: dict | None = None
) -> dict:
    """The agent a provider is handed, with project defaults laid under the workflow's."""
    workflow = WorkflowConfig.model_validate(
        {
            "name": "w",
            "description": "d",
            "defaults": {**BASE, **(defaults or {})},
            "actions": [{"name": "act", "intent": "i", "kind": "llm", **(action or {})}],
        }
    )
    expanded = {
        "name": "w",
        "actions": [
            a.model_dump(mode="python", exclude_unset=True, by_alias=True) for a in workflow.actions
        ],
        "defaults": {
            **(project or {}),
            **workflow.defaults.model_dump(mode="python", exclude_unset=True, by_alias=True),
        },
    }
    agent = ActionExpander.expand_actions_to_agents(expanded)["w"][0]
    manager = ConfigManager.__new__(ConfigManager)
    manager.default_config = {"default_agent_config": project} if project else {}
    manager.tool_path = None
    manager.agent_configs = {}
    manager.merge_agent_configs([agent])
    return manager.agent_configs["act"].model_dump()


class TestWhereItIsSet:
    def test_unset_everywhere_it_is_none(self):
        assert _agent()["request_timeout"] is None

    def test_an_action_sets_it(self):
        assert _agent(action={"request_timeout": 45})["request_timeout"] == 45

    def test_a_workflow_default_reaches_an_action_that_does_not_set_it(self):
        assert _agent(defaults={"request_timeout": 30})["request_timeout"] == 30

    def test_a_project_default_reaches_an_action_that_does_not_set_it(self):
        assert _agent(project={"request_timeout": 20})["request_timeout"] == 20

    def test_the_workflow_default_outranks_the_project_default(self):
        agent = _agent(project={"request_timeout": 20}, defaults={"request_timeout": 30})

        assert agent["request_timeout"] == 30

    def test_an_action_outranks_both_defaults(self):
        agent = _agent(
            project={"request_timeout": 20},
            defaults={"request_timeout": 30},
            action={"request_timeout": 2.5},
        )

        assert agent["request_timeout"] == 2.5


def _refused(model, value) -> str:
    payload = {"name": "a", "intent": "i"} if model is ActionConfig else dict(BASE)
    with pytest.raises(ValidationError) as excinfo:
        model.model_validate({**payload, "request_timeout": value})
    return "; ".join(f"{e['loc'][-1]}: {e['msg']}" for e in excinfo.value.errors())


SURFACES = [ActionConfig, DefaultsConfig, AgentConfig, DefaultAgentConfig]


class TestWhatItTakes:
    @pytest.mark.parametrize("model", SURFACES)
    @pytest.mark.parametrize("value", [0, -1, -0.5])
    def test_zero_or_a_negative_number_is_refused(self, model, value):
        if model is AgentConfig:
            with pytest.raises(ValidationError, match="request_timeout"):
                AgentConfig.model_validate({"agent_type": "a", "request_timeout": value})
            return
        assert "request_timeout: Input should be greater than 0" in _refused(model, value)

    @pytest.mark.parametrize("model", [ActionConfig, DefaultsConfig, DefaultAgentConfig])
    @pytest.mark.parametrize("value", ["30", "soon", True, float("inf"), float("nan")])
    def test_anything_but_a_finite_number_is_refused(self, model, value):
        assert _refused(model, value).startswith("request_timeout:")

    @pytest.mark.parametrize("model", [ActionConfig, DefaultsConfig])
    @pytest.mark.parametrize("value", [1, 0.5, 600])
    def test_a_positive_number_of_seconds_is_taken(self, model, value):
        payload = {"name": "a", "intent": "i"} if model is ActionConfig else dict(BASE)

        assert model.model_validate({**payload, "request_timeout": value}).request_timeout == value

    def test_a_project_default_that_is_not_positive_is_refused_at_load(self):
        with pytest.raises((ValidationError, ConfigurationError), match="request_timeout"):
            _agent(project={"request_timeout": 0})


class TestItDoesNotChangeTheAnswers:
    def test_the_config_an_action_answers_under_ignores_it(self):
        without = _agent()
        with_timeout = _agent(action={"request_timeout": 5})

        assert config_in_force(with_timeout) == config_in_force(without)

    def test_changing_it_is_not_an_edit(self):
        stamp = config_in_force(_agent(action={"request_timeout": 5}))

        assert _edits_since(stamp, _agent(action={"request_timeout": 90})) == []
