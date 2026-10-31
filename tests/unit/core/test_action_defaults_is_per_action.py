"""The action's own `defaults:` is carried; nothing else is mistaken for it."""

from tests.unit.core.test_action_defaults_reaches_the_agent import _agents, _workflow


def test_a_version_expanded_action_carries_it_on_every_version():
    agents = _agents(
        _workflow(
            defaults={"output_path": "/out.jsonl"},
            versions={"param": "i", "range": [1, 2]},
        )
    )

    versions = [a for name, a in agents.items() if name.startswith("writer")]
    assert len(versions) == 2
    assert [a["defaults"] for a in versions] == [{"output_path": "/out.jsonl"}] * 2


def test_a_sibling_action_does_not_receive_it():
    agents = _agents(_workflow(defaults={"output_path": "/out.jsonl"}))

    assert "defaults" not in agents["extract"]


def test_an_empty_defaults_declares_nothing_and_changes_no_gap():
    from agent_actions.validation.dag_schema_fit_validator import (
        find_dag_schema_compatibility_gaps,
    )

    with_empty = find_dag_schema_compatibility_gaps(_agents(_workflow(defaults={})))
    without = find_dag_schema_compatibility_gaps(_agents(_workflow()))

    assert with_empty == without == {"writer": ["output_path", "written_count"]}
