"""An action's `defaults:` reaches the loaded agent, so the dag-fit check can read it."""

from agent_actions.config.manager import ConfigManager
from agent_actions.validation.dag_schema_fit_validator import (
    find_dag_schema_compatibility_gaps,
)


def _agents(actions: list[dict]) -> dict[str, dict]:
    manager = ConfigManager("test_workflow.yml", "")
    manager.user_config = {
        "name": "test_workflow",
        "description": "test",
        "version": "1",
        "defaults": {"model_vendor": "agac-provider", "model_name": "mock", "api_key": "KEY"},
        "actions": actions,
    }
    return {agent["agent_type"]: agent for agent in manager.get_user_agents()}


def _workflow(**writer: object) -> list[dict]:
    return [
        {"name": "extract", "intent": "do", "kind": "llm"},
        {
            "name": "writer",
            "intent": "do",
            "kind": "tool",
            "impl": "write_rows",
            "dependencies": ["extract"],
            "schema": {
                "fields": [
                    {"id": "output_path", "type": "string", "required": True},
                    {"id": "written_count", "type": "number", "required": True},
                ]
            },
            **writer,
        },
    ]


def test_the_declared_defaults_are_on_the_loaded_agent():
    agents = _agents(_workflow(defaults={"output_path": "/out.jsonl"}))

    assert agents["writer"]["defaults"] == {"output_path": "/out.jsonl"}


def test_an_action_without_defaults_carries_none():
    agents = _agents(_workflow())

    assert not agents["writer"].get("defaults")
    assert not agents["extract"].get("defaults")


def test_the_dag_fit_check_excludes_a_field_the_loaded_action_declares():
    declared = _agents(_workflow(defaults={"output_path": "/out.jsonl"}))
    undeclared = _agents(_workflow())

    assert find_dag_schema_compatibility_gaps(undeclared) == {
        "writer": ["output_path", "written_count"]
    }
    assert find_dag_schema_compatibility_gaps(declared) == {"writer": ["written_count"]}
