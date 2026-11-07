"""Pre-flight refuses a `schema: dispatch_task(...)` the run could not resolve.

The run finds the function as a file named for it under the tools path, defining a
function of that name. A name with no such file would otherwise fail only once records
were sent. Online and batch both resolve it per record, so both are held to this alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.services.preflight_service import PreflightService

TOOL = """\
def pick_schema(context_json):
    return {"topic": "string"}
"""


def _check(tmp_path: Path, function: str, **config) -> None:
    tools = tmp_path / "tools" / "wf"
    tools.mkdir(parents=True, exist_ok=True)
    (tools / "pick_schema.py").write_text(TOOL)
    action = {
        "schema": f"dispatch_task('{function}')",
        "schema_options": ["topic_answer"],
        "tool_path": [str(tmp_path / "tools")],
        "run_mode": "online",
        **config,
    }
    PreflightService("wf", {"label_page": action}, tmp_path, "wf.yml")._check_schema_dispatches()


def test_a_function_a_tool_file_defines_passes(tmp_path):
    _check(tmp_path, "pick_schema")


def test_a_function_no_tool_file_defines_is_refused(tmp_path):
    with pytest.raises(PreFlightValidationError) as refused:
        _check(tmp_path, "no_such_fn")

    assert (
        "Action 'label_page' dispatches its schema to 'no_such_fn', and no tool file "
        "defines it: dispatch_task looks for no_such_fn.py with a function no_such_fn under "
    ) in str(refused.value)


def test_a_file_without_the_function_is_refused(tmp_path):
    (tmp_path / "tools" / "wf").mkdir(parents=True)
    (tmp_path / "tools" / "wf" / "other.py").write_text("def unrelated(x):\n    return x\n")

    with pytest.raises(PreFlightValidationError, match="dispatches its schema to 'other'"):
        _check(tmp_path, "other")


def test_a_dispatched_schema_in_batch_passes(tmp_path):
    _check(tmp_path, "pick_schema", run_mode="batch")


def test_a_missing_function_in_batch_is_refused_too(tmp_path):
    with pytest.raises(PreFlightValidationError, match="dispatches its schema to 'no_such_fn'"):
        _check(tmp_path, "no_such_fn", run_mode="batch")


def test_a_call_with_an_argument_is_looked_up_by_its_function(tmp_path):
    """The run splits the call on ',' and passes the rest as arguments."""
    _check(tmp_path, "pick_schema, strict")


def test_a_tool_file_that_fails_to_import_is_named_as_such(tmp_path):
    (tmp_path / "tools" / "wf").mkdir(parents=True)
    (tmp_path / "tools" / "wf" / "broken_pick.py").write_text("import no_such_module_here\n")

    with pytest.raises(PreFlightValidationError) as refused:
        _check(tmp_path, "broken_pick")

    assert "broken_pick.py could not be imported" in str(refused.value)
    assert "no tool file defines it" not in str(refused.value)


def test_add_dispatch_with_a_dispatched_schema_in_batch_is_refused(tmp_path):
    with pytest.raises(PreFlightValidationError) as refused:
        _check(tmp_path, "pick_schema", run_mode="batch", add_dispatch=True)

    assert "sets add_dispatch with a schema chosen by dispatch_task" in str(refused.value)


def test_add_dispatch_with_a_dispatched_schema_online_passes(tmp_path):
    _check(tmp_path, "pick_schema", add_dispatch=True)


@pytest.mark.parametrize("options", [None, []], ids=["absent", "empty"])
def test_a_dispatch_with_no_schema_options_is_refused(tmp_path, options):
    with pytest.raises(PreFlightValidationError) as refused:
        _check(tmp_path, "pick_schema", schema_options=options)

    assert (
        "Action 'label_page' takes its schema from dispatch_task('pick_schema') but declares "
        "no schema_options. List every schema name the function can return under schema_options."
    ) in str(refused.value)


def test_schema_options_without_a_dispatch_is_refused(tmp_path):
    with pytest.raises(PreFlightValidationError, match="sets schema_options, but its schema"):
        _check(tmp_path, "pick_schema", schema={"topic": "string"})


@pytest.mark.parametrize(
    "schema",
    [
        {"name": "s", "fields": [{"id": "topic", "type": "dispatch_task('pick_schema')"}]},
        {
            "name": "s",
            "fields": [
                {
                    "id": "detail",
                    "type": "object",
                    "properties": {"inner": {"type": "dispatch_task('pick_schema')"}},
                }
            ],
        },
    ],
    ids=["top_level", "nested"],
)
def test_a_dispatch_inside_schema_fields_is_refused_and_names_schema_options(tmp_path, schema):
    with pytest.raises(PreFlightValidationError) as refused:
        _check(tmp_path, "pick_schema", schema=schema, schema_options=None)

    message = str(refused.value)
    assert "calls dispatch_task inside its schema fields" in message
    assert "list the schemas it can return under schema_options" in message
