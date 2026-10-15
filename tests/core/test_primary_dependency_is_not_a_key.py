"""`primary_dependency` is not a key an action takes: no setting names a fan-in's primary."""

import typing

import pytest

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import ActionConfig
from agent_actions.config.types import ActionConfigDict
from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_inference import infer_dependencies


def _manager(actions: list[dict]) -> ConfigManager:
    manager = ConfigManager("test_workflow.yml", "")
    manager.user_config = {
        "name": "test_workflow",
        "description": "test",
        "version": "1",
        "defaults": {"model_vendor": "agac-provider", "model_name": "mock", "api_key": "KEY"},
        "actions": actions,
    }
    return manager


def _fan_in(**joined: object) -> list[dict]:
    return [
        {"name": "left", "intent": "do", "kind": "llm"},
        {"name": "right", "intent": "do", "kind": "llm"},
        {
            "name": "joined",
            "intent": "do",
            "kind": "llm",
            "dependencies": ["left", "right"],
            **joined,
        },
    ]


def test_an_action_that_sets_it_is_refused_as_any_unknown_key_is():
    with pytest.raises(ConfigurationError) as raised:
        _manager(_fan_in(primary_dependency="right")).get_user_agents()

    with pytest.raises(ConfigurationError) as unknown:
        _manager(_fan_in(no_such_key="right")).get_user_agents()

    assert "primary_dependency" in str(raised.value.__cause__)
    assert str(raised.value.__cause__) == str(unknown.value.__cause__).replace(
        "no_such_key", "primary_dependency"
    )


def test_the_same_fan_in_without_it_loads():
    agents = _manager(_fan_in()).get_user_agents()

    assert [agent["agent_type"] for agent in agents] == ["left", "right", "joined"]


def test_neither_the_action_model_nor_the_runtime_shape_declares_it():
    assert "primary_dependency" not in ActionConfig.model_fields
    assert "primary_dependency" not in typing.get_type_hints(ActionConfigDict)


@pytest.mark.parametrize("named", ["right", "left", "not_a_dependency"])
def test_a_config_carrying_it_splits_its_dependencies_as_one_without_it(named):
    config = {"dependencies": ["left", "right"], "context_scope": {"observe": ["left.*"]}}
    actions = ["left", "right", "joined"]

    with_key = infer_dependencies(
        {**config, "primary_dependency": named}, actions, "joined", validate=False
    )

    assert with_key == infer_dependencies(config, actions, "joined", validate=False)
    assert with_key == (["left", "right"], [])


def test_inspect_reports_a_fan_in_under_its_sources_and_scope_alone():
    from types import SimpleNamespace

    from agent_actions.cli.inspect_base import BaseInspectCommand

    inspector = SimpleNamespace(
        action_configs={
            "left": {},
            "right": {},
            "joined": {
                "dependencies": ["left", "right"],
                "context_scope": {"observe": ["left.*", "right.*"]},
            },
        }
    )

    info = BaseInspectCommand("wf", None, json_output=True)._analyze_dependencies(inspector)

    assert info["joined"] == {
        "explicit_dependencies": ["left", "right"],
        "input_sources": ["left", "right"],
        "context_sources": [],
        "context_scope": {"observe": ["left.*", "right.*"], "passthrough": [], "drop": []},
    }


def test_written_under_the_project_defaults_it_changes_no_fan_in():
    config = {"dependencies": ["left", "right"], "context_scope": {"observe": ["left.*"]}}
    actions = ["left", "right", "joined"]
    plain = infer_dependencies(config, actions, "joined")

    for value in ("right", "ghost", ["x"]):
        inherited = {**config, "primary_dependency": value}
        assert infer_dependencies(inherited, actions, "joined") == plain
