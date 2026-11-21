"""Tools agac runs itself: configured by the action's ``_builtin`` key, not written as a UDF.

``route`` writes ``{"case": <case>}``: the value of the ``field`` field when it is one of
``cases``, else ``default`` when the router has a default branch. ``pick`` writes the
output of the one action of ``of`` the record holds an output of.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_actions.errors import ConfigurationError

BUILTIN_KEY = "_builtin"
ROUTE = "route"
PICK = "pick"
BUILTIN_TOOLS = frozenset({ROUTE, PICK})
CASE_FIELD = "case"
DEFAULT_CASE = "default"


def builtin_tool(config: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The ``_builtin`` spec of a built-in tool action, or None for any other action."""
    spec = config.get(BUILTIN_KEY) if config is not None else None
    return spec if isinstance(spec, dict) and spec.get("tool") in BUILTIN_TOOLS else None


def is_router(config: Mapping[str, Any]) -> bool:
    spec = builtin_tool(config)
    return spec is not None and spec["tool"] == ROUTE


def runs_udf(config: Mapping[str, Any]) -> bool:
    """Whether *config* is a tool action whose ``impl`` names a UDF of the project."""
    return config.get("kind") == "tool" and builtin_tool(config) is None


def field_value(data: Mapping[str, Any], path: str) -> Any:
    """The value at ``<action>.<field>[.<field>...]`` of a record's action-keyed data.

    Raises ``KeyError`` naming *path* when the record does not hold it: a field the router
    does not read would send every record to the default branch.
    """
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise KeyError(f"the record holds no '{path}'; observe it on the router")
        value = value[part]
    return value


def route_case(spec: Mapping[str, Any], data: Mapping[str, Any]) -> str:
    value = field_value(data, spec["field"])
    if isinstance(value, str) and value in spec["cases"]:
        return value
    if spec.get("default"):
        return DEFAULT_CASE
    raise ValueError(
        f"{spec['field']} is {value!r}, which is no case of the router ({', '.join(spec['cases'])}) "
        "and the router has no default branch"
    )


def picked(spec: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    """The output of the one action of ``of`` the record holds an output of.

    Raises ``ValueError`` when more than one holds one: the record went down two branches.
    """
    held = [source for source in spec["of"] if isinstance(data.get(source), Mapping)]
    if len(held) > 1:
        raise ValueError(
            f"the record holds an output of {', '.join(held)}; pick takes the output of one of them"
        )
    return dict(data[held[0]]) if held else {}


def route_case_counts(
    config: Mapping[str, Any], action_name: str, rows: list[dict[str, Any]]
) -> dict[str, int] | None:
    """How many of a built-in router's *rows* hold each case; None for any other action."""
    spec = builtin_tool(config)
    if spec is None or spec["tool"] != ROUTE:
        return None
    counts = dict.fromkeys([*spec["cases"], *([DEFAULT_CASE] if spec.get("default") else [])], 0)
    for row in rows:
        content = row.get("content")
        output = content.get(action_name) if isinstance(content, dict) else None
        case = output.get(CASE_FIELD) if isinstance(output, dict) else None
        if isinstance(case, str):
            counts[case] = counts.get(case, 0) + 1
    return counts


def run_builtin(spec: Mapping[str, Any], data: Any) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ConfigurationError(
            f"The built-in tool '{spec['tool']}' reads one record at a time",
            context={"tool": spec["tool"], "input_type": type(data).__name__},
        )
    if spec["tool"] == ROUTE:
        return {CASE_FIELD: route_case(spec, data)}
    return picked(spec, data)
