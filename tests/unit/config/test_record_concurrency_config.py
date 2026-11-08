"""`record_concurrency` is set on an online LLM action, in `defaults:` or project-wide.

It reaches the agent the way `request_timeout` does and is refused at load outside 1-32.
Written on an action that cannot run records concurrently (tool, hitl, batch) it is
refused, naming the action and the reason; inherited by one, it is ignored.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import WorkflowConfig
from agent_actions.errors import ConfigValidationError
from agent_actions.output.response.expander import ActionExpander
from agent_actions.workflow.executor import _edits_since, config_in_force

BASE = {"model_vendor": "openai", "model_name": "gpt-4o-mini", "api_key": "KEY"}


def _llm(name: str = "act", **extra) -> dict:
    return {"name": name, "intent": "i", "kind": "llm", "prompt": "Answer.", **extra}


def _tool(name: str = "nap", **extra) -> dict:
    return {
        "name": name,
        "intent": "i",
        "kind": "tool",
        "impl": "nap",
        "schema": {"topic": "string"},
        **extra,
    }


def _hitl(name: str = "review", **extra) -> dict:
    return {"name": name, "intent": "i", "kind": "hitl", "hitl": {"instructions": "Ok."}, **extra}


def _agents(
    actions: list[dict], defaults: dict | None = None, project: dict | None = None
) -> dict[str, dict]:
    """Expanded agents, with project defaults laid under the workflow's as a run lays them."""
    workflow = WorkflowConfig.model_validate(
        {
            "name": "w",
            "description": "d",
            "defaults": {**BASE, **(defaults or {})},
            "actions": actions,
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
    return {a["agent_type"]: a for a in ActionExpander.expand_actions_to_agents(expanded)["w"]}


def _merged(agent: dict, project: dict | None = None) -> dict:
    manager = ConfigManager.__new__(ConfigManager)
    manager.default_config = {"default_agent_config": project} if project else {}
    manager.tool_path = None
    manager.agent_configs = {}
    manager.merge_agent_configs([agent])
    return manager.agent_configs[agent["agent_type"]].model_dump()


class TestWhereItIsSet:
    def test_unset_everywhere_it_is_none(self):
        assert _merged(_agents([_llm()])["act"])["record_concurrency"] is None

    def test_an_action_sets_it(self):
        assert _agents([_llm(record_concurrency=4)])["act"]["record_concurrency"] == 4

    def test_a_workflow_default_reaches_an_action(self):
        agents = _agents([_llm()], defaults={"record_concurrency": 5})

        assert agents["act"]["record_concurrency"] == 5

    def test_the_project_default_reaches_an_agent(self):
        project = {"record_concurrency": 3}
        merged = _merged(_agents([_llm()], project=project)["act"], project=project)

        assert merged["record_concurrency"] == 3


class TestOutOfRange:
    @pytest.mark.parametrize("value", [0, 33, True, 2.0, "4"])
    def test_an_action_value_outside_one_to_thirty_two_is_refused(self, value):
        with pytest.raises(ValidationError) as excinfo:
            _agents([_llm(record_concurrency=value)])

        assert "record_concurrency" in str(excinfo.value)

    def test_a_defaults_value_outside_the_range_is_refused(self):
        with pytest.raises(ValidationError):
            _agents([_llm()], defaults={"record_concurrency": 33})

    @pytest.mark.parametrize("value", [1, 32])
    def test_the_ends_of_the_range_load(self, value):
        assert _agents([_llm(record_concurrency=value)])["act"]["record_concurrency"] == value


class TestWhereItCannotApply:
    @pytest.mark.parametrize(
        ("action", "reason"),
        [
            (_tool(record_concurrency=4), "a tool action runs its records one at a time"),
            (_hitl(record_concurrency=4), "a hitl action reviews its records together"),
            (
                _llm(record_concurrency=4, run_mode="batch"),
                "a batch action's records run at the provider",
            ),
        ],
        ids=["tool", "hitl", "batch"],
    )
    def test_written_on_an_action_that_cannot_use_it_is_refused(self, action, reason):
        with pytest.raises(ConfigValidationError) as excinfo:
            _agents([action])

        name = action["name"]
        message = str(excinfo.value)
        assert f"Action '{name}' sets record_concurrency, but {reason}." in message
        assert f"Remove record_concurrency from '{name}'." in message

    def test_written_on_an_action_whose_inherited_mode_is_batch_is_refused(self):
        with pytest.raises(ConfigValidationError):
            _agents([_llm(record_concurrency=4)], defaults={"run_mode": "batch"})

    def test_inherited_by_a_tool_hitl_or_batch_action_is_ignored(self):
        agents = _agents(
            [_tool(), _hitl(), _llm("later", run_mode="batch"), _llm("now")],
            defaults={"record_concurrency": 4},
        )

        assert set(agents) == {"nap", "review", "later", "now"}
        assert agents["now"]["record_concurrency"] == 4


class TestNotAConfigEdit:
    def test_it_is_not_part_of_the_config_an_answer_is_stamped_under(self):
        with_key = _merged(_agents([_llm(record_concurrency=8)])["act"])
        without = _merged(_agents([_llm()])["act"])

        assert config_in_force(with_key) == config_in_force(without)

    def test_editing_it_is_not_an_edit_since_the_answers(self):
        stamp = config_in_force(_merged(_agents([_llm(record_concurrency=2)])["act"]))

        assert _edits_since(stamp, _merged(_agents([_llm(record_concurrency=9)])["act"])) == []
