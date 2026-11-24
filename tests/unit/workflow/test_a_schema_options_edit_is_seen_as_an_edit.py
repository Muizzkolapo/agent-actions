"""An edit to `schema_options` is reported as an edit, as an edit to the scope is."""

from __future__ import annotations

from agent_actions.workflow.executor import config_in_force, edits_since_its_work_began

BASE = {"schema": "dispatch_task('pick')", "prompt": "p", "model_name": "m", "model_vendor": "v"}


def test_a_changed_option_list_is_named_as_an_edit():
    stamp = config_in_force({**BASE, "schema_options": ["a", "b"]})

    edits = edits_since_its_work_began(
        {"answered_under": stamp}, {**BASE, "schema_options": ["a", "c"]}
    )

    assert edits == ["schema options"]


def test_the_same_option_list_is_not_an_edit():
    stamp = config_in_force({**BASE, "schema_options": ["a", "b"]})

    assert (
        edits_since_its_work_began(
            {"answered_under": stamp}, {**BASE, "schema_options": ["a", "b"]}
        )
        == []
    )


def test_options_added_to_an_action_without_them_are_an_edit():
    stamp = config_in_force(BASE)

    assert config_in_force(BASE)["schema_options_hash"] == ""
    assert edits_since_its_work_began(
        {"answered_under": stamp}, {**BASE, "schema_options": ["a"]}
    ) == ["schema options"]
