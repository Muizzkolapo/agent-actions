"""`context_window` is set on an action, in `defaults:` or in `default_agent_config:`.

It reaches each agent the way `request_timeout` does, is refused at load unless it is a
positive whole number of tokens, and is not part of the config an action's answers are
stamped under: it decides whether a prompt is sent, not what the answer is.
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import ActionConfig, DefaultsConfig, WorkflowConfig
from agent_actions.output.response.config_schema import AgentConfig, DefaultAgentConfig
from agent_actions.output.response.expander import ActionExpander
from agent_actions.workflow.executor import _edits_since, config_in_force

BASE = {"model_vendor": "anthropic", "model_name": "a-new-model", "api_key": "KEY"}


def _agent(
    *, project: dict | None = None, defaults: dict | None = None, action: dict | None = None
) -> dict:
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
            a.model_dump(mode="python", exclude_unset=True, by_alias=True)
            for a in workflow.actions
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
        assert _agent()["context_window"] is None

    def test_an_action_sets_it(self):
        assert _agent(action={"context_window": 400_000})["context_window"] == 400_000

    def test_a_workflow_default_reaches_an_action_that_does_not_set_it(self):
        assert _agent(defaults={"context_window": 300_000})["context_window"] == 300_000

    def test_a_project_default_reaches_an_action_that_does_not_set_it(self):
        assert _agent(project={"context_window": 200_000})["context_window"] == 200_000

    def test_an_action_outranks_both_defaults(self):
        agent = _agent(
            project={"context_window": 200_000},
            defaults={"context_window": 300_000},
            action={"context_window": 400_000},
        )

        assert agent["context_window"] == 400_000


SURFACES = [ActionConfig, DefaultsConfig, AgentConfig, DefaultAgentConfig]


def _payload(model) -> dict:
    if model is ActionConfig:
        return {"name": "a", "intent": "i"}
    if model is AgentConfig:
        return {"agent_type": "a"}
    return dict(BASE)


class TestWhatItTakes:
    @pytest.mark.parametrize("model", SURFACES)
    @pytest.mark.parametrize("value", [0, -1, "400000", 400_000.5, True])
    def test_anything_but_a_positive_whole_number_is_refused(self, model, value):
        with pytest.raises(ValidationError, match="context_window"):
            model.model_validate({**_payload(model), "context_window": value})

    @pytest.mark.parametrize("model", SURFACES)
    def test_a_positive_whole_number_is_taken(self, model):
        validated = model.model_validate({**_payload(model), "context_window": 400_000})

        assert validated.context_window == 400_000


class TestItDoesNotChangeTheAnswers:
    def test_changing_it_is_not_an_edit(self):
        stamp = config_in_force(_agent(action={"context_window": 400_000}))

        assert _edits_since(stamp, _agent(action={"context_window": 900_000})) == []
