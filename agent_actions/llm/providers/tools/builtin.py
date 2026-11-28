"""Tools agac runs itself: configured by the action's ``_builtin`` key, not written as a UDF.

``route`` writes ``{"case": <case>}``: the value of the ``field`` field when it is one of
``cases``, else ``default`` when the router has a default branch. ``pick`` writes the
output of the one action of ``of`` the record holds an output of. ``retrieve`` writes the
matches a search of a knowledge base finds for the record's query.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigurationError

BUILTIN_KEY = "_builtin"
ROUTE = "route"
PICK = "pick"
RETRIEVE = "retrieve"
BUILTIN_TOOLS = frozenset({ROUTE, PICK, RETRIEVE})
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


def field_value(
    data: Mapping[str, Any], path: str, hint: str = "; observe it on the router"
) -> Any:
    """The value at ``<action>.<field>[.<field>...]`` of a record's action-keyed data.

    Raises ``KeyError`` naming *path* when the record does not hold it: a field the router
    does not read would send every record to the default branch.
    """
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise KeyError(f"the record holds no '{path}'{hint}")
        value = value[part]
    return value


def route_case(spec: Mapping[str, Any], data: Mapping[str, Any]) -> str:
    value = field_value(data, spec["field"])
    if value is not None and not isinstance(value, str):
        raise TypeError(
            f"{spec['field']} holds {value!r} ({type(value).__name__}); "
            "a router matches strings only"
        )
    if isinstance(value, str) and value in spec["cases"]:
        return value
    if spec.get("default"):
        return DEFAULT_CASE
    raise ValueError(
        f"{spec['field']} is {value!r}, which is no case of the router "
        f"({', '.join(spec['cases'])}) "
        "and the router has no default branch"
    )


def picked(spec: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    """The output of the one action of ``of`` the record holds an output of.

    Raises ``ValueError`` when more than one holds one: the record went down two branches.
    A loop's result takes the first, its last iteration.
    """
    held = [source for source in spec["of"] if isinstance(data.get(source), Mapping)]
    # A loop's result lists its iterations last first, and a record holds the output of
    # every iteration it ran: the last one is its result.
    if len(held) > 1 and spec.get("loop") is None:
        raise ValueError(
            f"the record holds an output of {', '.join(held)}; pick takes the output of "
            "one of them"
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
    if spec["tool"] == RETRIEVE:
        return retrieved(spec, data)
    return picked(spec, data)


# -- retrieve ----------------------------------------------------------------


def retrieve_steps_of(action_configs: Mapping[str, Any], action: str) -> list[str]:
    """The retrieve steps the load generated for the context_scope.retrieve of *action*.

    A version (``score_1``) has the steps of its versioned action (``score``).
    """
    config = action_configs.get(action)
    base = config.get("version_base_name") if isinstance(config, Mapping) else None
    return [
        name
        for name, step in action_configs.items()
        if (spec := builtin_tool(step)) is not None
        and spec["tool"] == RETRIEVE
        and spec.get("action") in (action, base)
    ]


def step_label(spec: Mapping[str, Any], name: str) -> str:
    """How a message names a step: ``write_reply: retrieve 'help' (write_reply__help)``."""
    return f"{spec.get('action')}: retrieve '{spec.get('entry')}' ({name})"


def searched_indexes(spec: Mapping[str, Any]) -> tuple[str, frozenset[str]]:
    """The knowledge base a retrieve step searches and the index kinds its methods read.

    One digest covers one set of kinds, so a run resolves a digest for each such pair.
    """
    from agent_actions.knowledge.api import INDEX_FOR_METHOD

    return spec["base"], frozenset(INDEX_FOR_METHOD[method] for method in spec["methods"])


@dataclass
class KnowledgeRun:
    """What one run resolved for the knowledge bases its retrieve steps search."""

    project_root: Path
    sandbox: bool
    digests: dict[tuple[str, frozenset[str]], str] = field(default_factory=dict)
    hashes: dict[tuple[str, frozenset[str]], str | None] = field(default_factory=dict)
    warned: set[str] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)


_knowledge_run: KnowledgeRun | None = None


@contextmanager
def knowledge_run(project_root: Path, sandbox: bool) -> Iterator[KnowledgeRun]:
    """Hold one digest per knowledge base and index kinds for every pass of the run."""
    global _knowledge_run
    previous = _knowledge_run
    _knowledge_run = KnowledgeRun(project_root=project_root, sandbox=sandbox)
    try:
        yield _knowledge_run
    finally:
        _knowledge_run = previous


def resolve_knowledge(
    action_configs: Mapping[str, Any], project_root: Path, sandbox: bool
) -> None:
    """Build the stale indexes the retrieve steps of *action_configs* read, before any action.

    Each base and set of index kinds is resolved once per run; a later pass keeps the
    digest of the first.
    """
    global _knowledge_run
    wanted = {
        searched_indexes(spec)
        for config in action_configs.values()
        if (spec := builtin_tool(config)) is not None and spec["tool"] == RETRIEVE
    }
    if not wanted:
        return
    run = _knowledge_run
    if run is None or run.project_root != project_root or run.sandbox != sandbox:
        # A load outside a run command: its digests serve this load only.
        run = _knowledge_run = KnowledgeRun(project_root=project_root, sandbox=sandbox)
    from agent_actions.knowledge.api import ensure_indexes

    for key in sorted(wanted, key=lambda pair: (pair[0], sorted(pair[1]))):
        if key not in run.digests:
            base, indexes = key
            run.digests[key] = ensure_indexes(project_root, base, set(indexes), sandbox=sandbox)


def knowledge_hash(spec: Mapping[str, Any]) -> str | None:
    """The digest the indexes *spec* searches have in this run; None outside a run.

    Once the run resolved them, the digest its searches used: a later scan could see an
    edit made during the run, or fail.
    """
    run = _knowledge_run
    if run is None:
        return None
    from agent_actions.knowledge.api import knowledge_hash as current_hash

    key = searched_indexes(spec)
    with run.lock:
        if key in run.digests:
            return run.digests[key]
        if key not in run.hashes:
            run.hashes[key] = current_hash(
                run.project_root, key[0], set(key[1]), sandbox=run.sandbox
            )
        return run.hashes[key]


def first_knowledge_warning(step: str) -> bool:
    """Whether this run has not yet warned that the knowledge base of *step* changed."""
    run = _knowledge_run
    if run is None:
        return True
    with run.lock:
        first = step not in run.warned
        run.warned.add(step)
    return first


def query_words(value: Any, ref: str) -> list[str]:
    """The text a query reference adds: a null adds nothing, a list of strings is flattened."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [word for item in value for word in query_words(item, ref)]
    if isinstance(value, Mapping):
        raise TypeError(f"{ref} holds an object; a query reads text, numbers or lists of them")
    return [str(value)]


def _value_or_none(data: Mapping[str, Any], path: str) -> Any:
    """The value at *path* of the record, or None when the record does not hold it."""
    try:
        return field_value(data, path)
    except KeyError:
        return None


def retrieved(spec: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    """The matches the knowledge base of *spec* holds for the record's query."""
    hint = "; the retrieve step reads it from the record"
    words = [w for ref in spec["query"] for w in query_words(field_value(data, ref, hint), ref)]
    where = {
        name: value["value"] if isinstance(value, Mapping) else _value_or_none(data, value)
        for name, value in spec["where"].items()
    }
    label = step_label(spec, f"{spec['action']}__{spec['entry']}")
    for name, value in where.items():
        if isinstance(value, Mapping | list):
            kind = "a list" if isinstance(value, list) else "an object"
            raise TypeError(
                f"{label}: 'where: {{{name}: {spec['where'][name]}}}' holds {kind}; a where "
                "value is one text, number or boolean"
            )
    run = _knowledge_run
    digest = run.digests.get(searched_indexes(spec)) if run is not None else None
    if run is None or digest is None:
        raise ConfigurationError(
            f"{spec['action']}: retrieve '{spec['entry']}' searches knowledge base "
            f"'{spec['base']}', which this run did not build. Run the workflow with agac run.",
            context={"tool": RETRIEVE, "base": spec["base"]},
        )
    from agent_actions.knowledge.api import retrieve

    return retrieve(
        run.project_root,
        base=spec["base"],
        digest=digest,
        methods=dict(spec["methods"]),
        query_text=" ".join(words),
        where=where,
        top_k=spec["top_k"],
        candidates=spec["candidates"],
        max_context_tokens=spec["max_context_tokens"],
        max_per_origin=spec["max_per_origin"],
        label=label,
    )
