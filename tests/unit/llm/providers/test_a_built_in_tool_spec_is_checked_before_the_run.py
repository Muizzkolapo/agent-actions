"""The `_builtin` spec of a built-in tool is checked at load and in pre-flight, not at run time.

`agac inspect` validated a spec the tool could not run: a router with no `field`, cases as a
string or as numbers, a default of `"false"`, an unknown key, a pick of a string or of an
action it does not depend on, a misspelt tool, an `impl` that names another function, a
router per file, or a router on a field it does not observe.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig
from agent_actions.errors import PreFlightValidationError
from agent_actions.llm.providers.tools.builtin import run_builtin
from agent_actions.services.preflight_service import PreflightService

ROUTE = {"tool": "route", "field": "source.kind", "cases": ["a", "b"], "default": True}
PICK = {"tool": "pick", "of": ["on_a", "on_b"]}


def _action(spec: dict[str, Any], **over: Any) -> dict[str, Any]:
    action = {
        "name": "router" if spec.get("tool") == "route" else "joined",
        "kind": "tool",
        "impl": f"agac.{spec.get('tool')}",
        "intent": "x",
        "dependencies": ["on_a", "on_b"],
        "_builtin": spec,
    }
    action.update(over)
    return action


@pytest.mark.parametrize(
    "spec, words",
    [
        ({k: v for k, v in ROUTE.items() if k != "field"}, "field"),
        ({**ROUTE, "cases": "a,b"}, "cases"),
        ({**ROUTE, "cases": [1, 2]}, "cases"),
        ({**ROUTE, "default": "false"}, "default"),
        ({**ROUTE, "default": "filter"}, "default"),
        ({**ROUTE, "defualt": True}, "defualt"),
        ({**ROUTE, "cases": ["a", "default"]}, "names the default branch"),
        ({**PICK, "of": "on_a"}, "of"),
        ({**PICK, "of": []}, "of"),
        ({"tool": "rout", "field": "source.kind"}, "the built-in tools are pick, route"),
    ],
    ids=[
        "no-field",
        "cases-text",
        "cases-numbers",
        "default-text",
        "default-filter",
        "unknown-key",
        "case-named-default",
        "of-text",
        "of-empty",
        "unknown-tool",
    ],
)
def test_a_spec_the_tool_cannot_run_is_refused_at_load(spec, words):
    with pytest.raises(ValidationError, match=words):
        ActionConfig.model_validate(_action(spec))


@pytest.mark.parametrize("spec", [ROUTE, PICK], ids=["route", "pick"])
def test_a_valid_spec_loads(spec):
    assert ActionConfig.model_validate(_action(spec)).builtin == spec


def test_an_impl_that_names_another_function_is_refused():
    with pytest.raises(ValidationError, match="its 'impl' must be 'agac.route', not 'route'"):
        ActionConfig.model_validate(_action(ROUTE, impl="route"))


def test_a_pick_of_an_action_it_does_not_depend_on_is_refused():
    with pytest.raises(ValidationError, match="picks from on_c, which it does not depend on"):
        ActionConfig.model_validate(_action({"tool": "pick", "of": ["on_a", "on_c"]}))


def _preflight(config: dict[str, Any]) -> None:
    PreflightService("wf", {"router": config}, None, "wf.yml")._check_builtin_tools()


def test_a_built_in_tool_per_file_is_refused_in_pre_flight():
    config = {
        "_builtin": ROUTE,
        "granularity": "File",
        "context_scope": {"observe": ["source.kind"]},
    }

    with pytest.raises(PreFlightValidationError, match="reads one record at a time"):
        _preflight(config)


@pytest.mark.parametrize("observed", [["source.id"], [], ["source"]])
def test_a_router_on_a_field_it_does_not_observe_is_refused_in_pre_flight(observed):
    config = {"_builtin": ROUTE, "context_scope": {"observe": observed}}

    with pytest.raises(PreFlightValidationError, match="routes on 'source.kind'"):
        _preflight(config)


@pytest.mark.parametrize(
    "observed",
    ["source.kind", "source.*", "source.kind?", {"field": "source.kind", "optional": True}],
)
def test_a_router_that_observes_its_field_passes_pre_flight(observed):
    _preflight({"_builtin": ROUTE, "context_scope": {"observe": [observed]}})


NESTED = {**ROUTE, "field": "source.meta.kind"}


@pytest.mark.parametrize("observed", ["source.meta", "source.*"])
def test_a_router_on_a_nested_field_passes_when_it_observes_the_top_field(observed):
    _preflight({"_builtin": NESTED, "context_scope": {"observe": [observed]}})


@pytest.mark.parametrize("observed", ["source.meta.kind", "source"])
def test_a_router_on_a_nested_field_is_refused_for_an_observe_the_run_does_not_give(observed):
    config = {"_builtin": NESTED, "context_scope": {"observe": [observed]}}

    with pytest.raises(PreFlightValidationError, match="routes on 'source.meta.kind'"):
        _preflight(config)


def test_route_refuses_a_record_that_holds_no_value_at_its_field():
    with pytest.raises(KeyError, match="the record holds no 'source.kind'"):
        run_builtin(ROUTE, {"source": {"id": "r1"}})


def test_pick_refuses_a_record_that_holds_two_outputs():
    data = {"on_a": {"answer": "a"}, "on_b": {"answer": "b"}}

    with pytest.raises(ValueError, match="holds an output of on_a, on_b"):
        run_builtin(PICK, data)
