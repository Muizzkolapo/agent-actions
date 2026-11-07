"""Pre-flight refuses a `schema: dispatch_task(...)` the run could not resolve.

The run finds the function as a file named for it under the tools path, defining a
function of that name. A name with no such file, or a dispatched schema in batch, which
compiles one schema for every row, would otherwise fail only once records were sent.
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


def test_a_dispatched_schema_in_batch_is_refused(tmp_path):
    with pytest.raises(PreFlightValidationError) as refused:
        _check(tmp_path, "pick_schema", run_mode="batch")

    assert (
        "Action 'label_page' takes its schema from dispatch_task, which runs once per "
        "record and is supported only with run_mode: online."
    ) in str(refused.value)


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
