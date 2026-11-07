"""`schema: dispatch_task('fn')` chooses a schema per record; no route treats it as a file name.

The render step, the run's entry builder, the expander and the static analyzer each filed
the string as a schema name, so the run looked for a file called `dispatch_task('fn')`.
"""

from __future__ import annotations

import logging

import pytest

from agent_actions.errors import ConfigurationError, SchemaDispatchError
from agent_actions.output.response.context_data import _dispatched_schema
from agent_actions.output.response.dispatch_injection import schema_dispatch_function
from agent_actions.output.response.expander_schema import (
    compile_output_schema,
    process_schema_config,
)
from agent_actions.prompt.render_workflow import _compile_action_schemas
from agent_actions.prompt.renderer import ConfigRenderingService
from agent_actions.validation.static_analyzer.schema_extractor import SchemaExtractor

DISPATCH = "dispatch_task('pick_schema')"


@pytest.mark.parametrize(
    ("value", "function"),
    [
        (DISPATCH, "pick_schema"),
        ('  dispatch_task( "pick_schema" ) ', "pick_schema"),
        ("dispatch_task('tools.pick')", "tools.pick"),
        ("pick_schema", None),
        ("prefix dispatch_task('pick_schema')", None),
        ({"topic": "string"}, None),
        (None, None),
    ],
)
def test_only_a_whole_dispatch_call_is_a_schema_dispatch(value, function):
    assert schema_dispatch_function(value) == function


def test_the_expander_keeps_it_as_the_schema():
    agent: dict = {}
    process_schema_config(agent, {"schema": DISPATCH}, lambda value: value)

    assert agent == {"schema": DISPATCH}


def test_a_plain_name_still_becomes_a_schema_name():
    agent: dict = {}
    process_schema_config(agent, {"schema": "page_label"}, lambda value: value)

    assert agent == {"schema_name": "page_label"}


def test_compiling_the_output_schema_skips_it_without_a_warning(caplog):
    agent = {"agent_type": "label_page", "schema": DISPATCH}
    with caplog.at_level(logging.WARNING):
        compile_output_schema(agent, {})

    assert "json_output_schema" not in agent
    assert not [r for r in caplog.records if "unsupported type" in r.getMessage()]


def test_the_run_entry_files_it_under_schema():
    entry = ConfigRenderingService._build_agent_entry_from_action(
        object.__new__(ConfigRenderingService), {"name": "label_page", "schema": DISPATCH}
    )

    assert entry["schema"] == DISPATCH
    assert "schema_name" not in entry


def test_the_render_step_leaves_it_alone(caplog):
    action = {"name": "label_page", "schema": DISPATCH}
    with caplog.at_level(logging.WARNING):
        _compile_action_schemas(action)

    assert action["schema"] == DISPATCH
    assert not [r for r in caplog.records if "Could not load schema" in r.getMessage()]


@pytest.mark.parametrize("kind", ["llm", "tool"])
def test_the_static_analyzer_treats_it_as_chosen_at_run_time(kind):
    config = {"name": "label_page", "kind": kind, "schema": DISPATCH}
    if kind == "tool":
        config["impl"] = "label"

    output = SchemaExtractor(tool_schemas={}).extract_schema(config)

    assert output.is_dynamic is True
    assert output.load_error is None


def test_a_dispatch_function_may_return_a_mapping():
    assert _dispatched_schema("pick_schema", {"topic": "string"}, None) == {"topic": "string"}


@pytest.mark.parametrize("returned", [None, 3, ["topic"]])
def test_any_other_return_fails_the_record_with_what_to_return(returned):
    """Not a configuration error: online and batch fail this record alone, not the action."""
    with pytest.raises(SchemaDispatchError) as refused:
        _dispatched_schema("pick_schema", returned, None)

    assert not isinstance(refused.value, ConfigurationError)

    assert str(refused.value) == (
        f"dispatch_task('pick_schema') in schema returned {returned!r}; "
        "return a schema mapping or the name of a schema file."
    )


def _defects(expect: dict, tmp_path) -> list[str]:
    from agent_actions.validation.expectations_validator import find_expectation_defects

    action = {"name": "label_page", "schema": DISPATCH, "expect": expect}
    found = find_expectation_defects({"label_page": action}, {}, project_root=tmp_path)
    return found.get("label_page", [])


def test_a_repair_policy_names_the_dispatch_as_the_reason_it_cannot_run(tmp_path):
    defects = _defects({"repair": "auto", "expectations": [{"type": "no_null_fields"}]}, tmp_path)

    assert any("chosen per record by dispatch_task" in d for d in defects), defects
    assert not any("non-mapping schema" in d for d in defects), defects


def test_a_bare_expect_names_the_dispatch_as_the_reason_it_has_no_rules(tmp_path):
    defects = _defects({"repair": "none"}, tmp_path)

    assert any("schema is chosen per record by dispatch_task" in d for d in defects), defects
    assert not any("declares no schema" in d for d in defects), defects


def test_inline_rules_without_repair_are_accepted(tmp_path):
    assert (
        _defects({"repair": "none", "expectations": [{"type": "no_null_fields"}]}, tmp_path) == []
    )


def _entry_errors(schema) -> list[str]:
    from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
        ActionEntryValidationOrchestrator,
    )

    orchestrator = ActionEntryValidationOrchestrator()
    orchestrator.validate_action_entry(
        {"name": "label_page", "agent_type": "label_page", "model_name": "m", "schema": schema},
        "wf",
    )
    return [e for e in orchestrator.get_validation_errors() if "'schema'" in e]


def test_the_run_entry_validator_accepts_a_dispatch_call():
    assert _entry_errors(DISPATCH) == []


def test_the_run_entry_validator_still_refuses_any_other_string():
    assert _entry_errors("not a mapping") != []
