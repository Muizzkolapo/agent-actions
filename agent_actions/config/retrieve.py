"""Expand the ``context_scope.retrieve`` entries of each action into internal retrieve steps.

Each entry ``<entry>`` of action ``<action>`` becomes a built-in ``retrieve`` tool action
named ``<action>__<entry>``: it searches a knowledge base, or the records an earlier action
processed (``from: <action>``), for each record and writes the matches. The action depends
on the step and observes ``<step>.*``. In the action's prompt, guard and ``context_scope``
lists, ``retrieve.<entry>`` is an alias of the step, which the load writes as the step's name,
so every later check sees an ordinary action.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agent_actions.config.path_config import load_project_config, resolve_project_root
from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.tools.builtin import (
    BUILTIN_KEY,
    RETRIEVE,
    ROUTE,
    builtin_tool,
)
from agent_actions.record.elsewhere import SENDS_ELSEWHERE_KEY

RETRIEVE_KEY = "retrieve"
RETRIEVE_IMPL = "agac.retrieve"
ENTRY_KEYS = (
    "from",
    "method",
    "query",
    "where",
    "top_k",
    "candidates",
    "max_context_tokens",
    "max_per_origin",
)
# Keys of a retrieve from an action's records; on a base, its sources set them.
SOURCE_KEYS = ("text", "title", "id")
CORPUS_KEYS = tuple(key for key in (*ENTRY_KEYS, *SOURCE_KEYS) if key != "max_per_origin")
DEFAULT_METHOD = "keyword"
KEY_METHOD = "key"
DEFAULT_TOP_K = 5
MAX_TOP_K = 50
MAX_CANDIDATES = 1000
# Marks an action with entries until the prompt pass writes their alias as step names.
_STEPS_KEY = "_retrieve_steps"
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
_VERSION_SUFFIX = re.compile(r"_\d+\Z")
_ROUTE_GUARD = re.compile(r'\A(?P<router>[A-Za-z_][A-Za-z0-9_]*)\.case == "[^"]*"\Z')
_TOKEN = re.compile(
    r"""(?P<string>"(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?)"""
    r"|(?P<number>[0-9][A-Za-z0-9_.]*)"
    r"|(?P<path>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)
_JINJA_TAG = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
# Prompt text the alias never rewrites: a raw block and a comment.
_KEPT_TEXT = re.compile(
    r"\{%[-+]?\s*raw\s*[-+]?%\}.*?\{%[-+]?\s*endraw\s*[-+]?%\}|\{#.*?#\}", re.DOTALL
)
_SCOPE_LISTS = ("observe", "passthrough", "drop")

MATCH_FIELDS = {
    "id": {"type": "string"},
    "rank": {"type": "integer"},
    "score": {"type": "number"},
    "text": {"type": "string"},
    "title": {"type": "string"},
    "origin": {"type": "string"},
    "hash": {"type": "string"},
    "metadata": {"type": "object"},
}


def step_name(action: str, entry: str) -> str:
    return f"{action}__{entry}"


def output_schema(name: str) -> dict[str, Any]:
    """The fixed output schema of a retrieve step."""
    return {
        "name": f"{name}_matches",
        "fields": [
            {
                "id": "matches",
                "type": "array",
                "required": True,
                "items": {
                    "type": "object",
                    "properties": copy.deepcopy(MATCH_FIELDS),
                    "required": list(MATCH_FIELDS),
                    "additionalProperties": False,
                },
            },
            {"id": "count", "type": "integer", "required": True},
            {"id": "query", "type": "string", "required": True},
            {"id": "index", "type": "string", "required": True},
        ],
        "additionalProperties": False,
    }


def expand_retrieves(data: Any, workflow_file: str, project_root: Path | None = None) -> Any:
    """*data* with a retrieve step before each action for each of its retrieve entries."""
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        return data
    _refuse_in_defaults(data, workflow_file, project_root)
    # A workflow with no entry loads as it would without this feature.
    if not any(_entries_of(e) for e in actions):
        return data
    names = {e["name"] for e in actions if isinstance(e, dict) and isinstance(e.get("name"), str)}
    if RETRIEVE_KEY in names:
        raise ConfigurationError(
            f"Action '{RETRIEVE_KEY}' in {workflow_file}: '{RETRIEVE_KEY}' cannot name an "
            "action of a workflow that has context_scope.retrieve entries. A prompt or guard "
            f"reads '{RETRIEVE_KEY}.<entry>' as an entry of its action's context_scope.retrieve.",
            context={"action_name": RETRIEVE_KEY},
        )
    data = copy.deepcopy(data)
    actions = data["actions"]
    graph = _read_graph(actions)
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    from agent_actions.config.includes import inherited_granularities

    workflow = _Workflow(
        graph, _entries_by_name(actions), defaults, inherited_granularities(data, project_root)
    )
    taken = set(graph)
    bases: dict[str, Any] | None = None
    expanded: list[Any] = []
    for entry in actions:
        raw = _entries_of(entry)
        if not raw:
            expanded.append(entry)
            continue
        if bases is None:
            from agent_actions.knowledge.api import load_knowledge_config

            bases = load_knowledge_config(resolve_project_root(project_root))
        where = f"Action '{entry['name']}' in {workflow_file}"
        upstream = _upstream(entry["name"], graph)
        steps: dict[str, str] = {}
        for entry_name, config in raw.items():
            step = _step(
                entry, str(entry_name), config, bases, workflow, upstream, taken, workflow_file
            )
            steps[str(entry_name)] = step["name"]
            expanded.append(step)
        _wire_action(entry, steps, where)
        expanded.append(entry)
    data["actions"] = expanded
    _copy_guards(expanded)
    _refuse_alias_without_entries(expanded, workflow_file)
    return data


def finish_retrieve_routes(data: Any) -> None:
    """Give each retrieve step its action's route-entry status, once routes are expanded.

    A router guards the first action of each branch on its case; the step that action reads
    must take the same guard, so that a record sent elsewhere is not searched for.
    """
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        return
    by_name = {
        a["name"]: a for a in actions if isinstance(a, dict) and isinstance(a.get("name"), str)
    }
    for step in by_name.values():
        spec = builtin_tool(step)
        if spec is None or spec["tool"] != RETRIEVE or step.get("guard") is not None:
            continue
        action = by_name.get(spec["action"])
        guard = action.get("guard") if action is not None else None
        condition = guard.get("condition") if isinstance(guard, dict) else None
        match = _ROUTE_GUARD.match(condition) if isinstance(condition, str) else None
        if action is None or match is None or not action.get(SENDS_ELSEWHERE_KEY):
            continue
        router = match.group("router")
        if (builtin_tool(by_name.get(router)) or {}).get("tool") != ROUTE:
            continue
        step["guard"] = copy.deepcopy(guard)
        step[SENDS_ELSEWHERE_KEY] = True
        _add_dependencies(step, [router])
        _add_observe(step, [f"{router}.case"])


def alias_retrieve_prompts(data: Any, workflow_file: str) -> None:
    """Write ``retrieve.<entry>`` in each prompt as the name of the step it aliases.

    Runs once prompts are resolved, only on actions that have entries; refuses an alias of
    no entry of the action, and a prompt that binds the name ``retrieve`` itself.
    """
    actions = data.get("actions") if isinstance(data, dict) else None
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        steps = action.pop(_STEPS_KEY, None)
        prompt = action.get("prompt")
        if steps and isinstance(prompt, str) and RETRIEVE_KEY in prompt:
            where = f"Action '{action.get('name')}' in {workflow_file}: its prompt"
            _refuse_local_retrieve(prompt, where)
            action["prompt"] = _aliased_prompt(prompt, steps, where)


def _aliased_prompt(prompt: str, steps: Mapping[str, str], where: str) -> str:
    """*prompt* with the alias written as step names inside each Jinja tag.

    Text in a ``{% raw %}`` block or a ``{# #}`` comment is kept as written.
    """

    def aliased(text: str) -> str:
        return _JINJA_TAG.sub(lambda tag: _aliased(tag.group(0), steps, where), text)

    pieces: list[str] = []
    pos = 0
    for kept in _KEPT_TEXT.finditer(prompt):
        pieces += [aliased(prompt[pos : kept.start()]), kept.group(0)]
        pos = kept.end()
    pieces.append(aliased(prompt[pos:]))
    return "".join(pieces)


def _refuse_local_retrieve(prompt: str, where: str) -> None:
    """Refuse a prompt that binds ``retrieve`` (set, for, with, macro, import)."""
    import jinja2
    from jinja2 import nodes

    from agent_actions.prompt.cache_point import PROMPT_EXTENSIONS

    env = jinja2.Environment(extensions=PROMPT_EXTENSIONS)  # nosec B701  # parsed, never rendered
    try:
        ast = env.parse(prompt)
    except jinja2.TemplateError:
        return  # The load reports a prompt that does not parse.
    names = [n.name for n in ast.find_all(nodes.Name) if n.ctx in ("store", "param")]
    names += [m.name for m in ast.find_all(nodes.Macro)]
    names += [i.target for i in ast.find_all(nodes.Import)]
    names += [
        n if isinstance(n, str) else n[1] for i in ast.find_all(nodes.FromImport) for n in i.names
    ]
    if RETRIEVE_KEY in names:
        raise ConfigurationError(
            f"{where} binds '{RETRIEVE_KEY}' itself (with set, for, with, macro or import). "
            f"In an action with context_scope.retrieve entries, '{RETRIEVE_KEY}' names those "
            "entries: give the local name another name.",
        )


# -- one entry ---------------------------------------------------------------


class _Workflow:
    """What an entry is checked against: the read graph, each entry by name, the defaults."""

    def __init__(
        self,
        graph: Mapping[str, list[str]],
        entries: Mapping[str, dict[str, Any]],
        defaults: Mapping[str, Any],
        granularities: Mapping[str, Any] | None = None,
    ):
        self.graph = graph
        self.entries = entries
        self.defaults = dict(defaults)
        # Each action's granularity with the workflow and project defaults applied.
        self.granularities = dict(granularities or {})


def _step(
    action: dict[str, Any],
    entry: str,
    config: Any,
    bases: Mapping[str, Any],
    workflow: _Workflow,
    upstream: set[str],
    taken: set[str],
    workflow_file: str,
) -> dict[str, Any]:
    graph = workflow.graph
    name = action["name"]
    where = f"Action '{name}' in {workflow_file}: context_scope.retrieve.{entry}"
    if not isinstance(entry, str) or not _NAME.match(entry):
        raise ConfigurationError(
            f"{where}: an entry name must start with a letter and hold only letters, digits "
            "and '_'.",
            context={"action_name": name, "entry": repr(entry)},
        )
    if "__" in entry or entry.endswith("_") or _VERSION_SUFFIX.search(entry):
        raise ConfigurationError(
            f"{where}: an entry name cannot contain '__', end with '_', or end with '_' and "
            "digits, which reads as a version.",
            context={"action_name": name, "entry": entry},
        )
    step = step_name(name, entry)
    if step in taken:
        raise ConfigurationError(
            f"{where}: its step is named '{step}', which is already an action of the workflow. "
            "Rename the entry or the action.",
            context={"action_name": name, "entry": entry, "step": step},
        )
    taken.add(step)
    where = f"{name}: retrieve '{entry}' ({step}) in {workflow_file}"
    if not isinstance(config, dict):
        raise ConfigurationError(
            f"{where}: the entry must be a mapping with 'from:' and 'query:'.",
            context={"action_name": name, "entry": entry},
        )
    source = config.get("from")
    if not isinstance(source, str) or not source:
        raise ConfigurationError(
            f"{where}: 'from:' must name the knowledge base, or the earlier action, to search.",
            context={"action_name": name, "entry": entry},
        )
    names = _instance_names(action)
    corpus = _corpus(config, names.get(source, source), source, bases, workflow, upstream, where)
    base = None
    if corpus is None:
        _refuse_unknown_keys(config, where)
        base = bases.get(source)
        if base is None:
            from agent_actions.knowledge.config import unknown_base_message

            raise ConfigurationError(
                f"{where}: {unknown_base_message(source, bases)}",
                context={"action_name": name, "entry": entry, "from": source},
            )
        methods = _methods(config.get("method", DEFAULT_METHOD), base, where)
        fields = base.metadata_fields
        about = f"knowledge base '{base.name}'"
    else:
        methods = _corpus_methods(config.get("method", DEFAULT_METHOD), where)
        # The text fields are searched; `where` compares the others whole.
        fields = None
        about = f"action '{corpus['action']}' outside its text fields"
    query = _query(config.get("query"), names, graph, upstream, where)
    searched = corpus["text"] if corpus is not None else []
    filters = _where(config.get("where"), fields, about, searched, names, graph, upstream, where)
    top_k = _whole(config, "top_k", DEFAULT_TOP_K, 1, MAX_TOP_K, where)
    candidates = _whole(config, "candidates", max(20, 4 * top_k), top_k, MAX_CANDIDATES, where)
    refs = [*query, *(ref for ref in filters.values() if isinstance(ref, str))]
    readers = list(dict.fromkeys(ref.split(".", 1)[0] for ref in refs))
    # A null or missing `where` ref matches nothing; it never fails the record.
    observe = [ref if ref in query else f"{ref}?" for ref in dict.fromkeys(refs)]
    spec: dict[str, Any] = {
        "tool": RETRIEVE,
        **({"base": source} if corpus is None else {"corpus": corpus}),
        "methods": methods,
        "query": query,
        "where": filters,
        "top_k": top_k,
        "candidates": candidates,
        "max_context_tokens": _whole(config, "max_context_tokens", None, 1, None, where),
        "max_per_origin": _whole(config, "max_per_origin", None, 1, None, where),
        "entry": entry,
        "action": name,
    }
    built: dict[str, Any] = {
        "name": step,
        "kind": "tool",
        "impl": RETRIEVE_IMPL,
        "granularity": "record",
        "intent": f"Retrieve from knowledge base {source} for {name}"
        if corpus is None
        else f"Retrieve from the records of action {corpus['action']} for {name}",
        "schema": output_schema(step),
        "context_scope": {"observe": observe},
        BUILTIN_KEY: spec,
    }
    # The action's own dependencies first: upstream filters, cascades and route branches
    # reach the step exactly as they reach the action.
    dependencies = list(_dependencies_of(action))
    dependencies += [r for r in readers if r != "source" and r not in dependencies]
    if corpus is not None and corpus["action"] not in dependencies:
        dependencies.append(corpus["action"])
    if dependencies:
        built["dependencies"] = dependencies
        # Each dependency must be named in the scope; a wildcard never fails a record.
        _add_observe(built, [f"{d}.*" for d in dependencies if d not in readers])
    if "version_consumption" in action:
        built["version_consumption"] = copy.deepcopy(action["version_consumption"])
    if "_include" in action:
        built["_include"] = copy.deepcopy(action["_include"])
    return built


def _corpus(
    config: Mapping[str, Any],
    source: str,
    written: str,
    bases: Mapping[str, Any],
    workflow: _Workflow,
    upstream: set[str],
    where: str,
) -> dict[str, Any] | None:
    """What a step reads of each record of the action *source* names; None for a base."""
    graph = workflow.graph
    versioned = _VERSION_SUFFIX.sub("", source)
    group = workflow.entries.get(versioned) if versioned != source else None
    if source not in graph and not (isinstance(group, dict) and "versions" in group):
        return None
    context = {"from": written}
    if written in bases:
        raise ConfigurationError(
            f"{where}: 'from: {written}' names both a knowledge base of agent_actions.yml and "
            "an action of the workflow. Rename one of them.",
            context=context,
        )
    found = workflow.entries.get(source, group)
    _refuse_corpus_kind(found, source, versioned, workflow, where)
    if source not in upstream:
        raise ConfigurationError(
            f"{where}: 'from: {written}' names an action that is not upstream of the action. "
            "A retrieve step searches the records of an action the action depends on.",
            context=context,
        )
    unknown = sorted(str(key) for key in config if key not in CORPUS_KEYS)
    if unknown:
        refused = "max_per_origin" in unknown
        raise ConfigurationError(
            f"{where}: "
            + (
                "'max_per_origin' does not apply to the records of one action, which all "
                "have one origin."
                if refused
                else f"unknown key {', '.join(unknown)}. Keys: {', '.join(CORPUS_KEYS)}."
            ),
            context={"unknown_keys": unknown},
        )
    text = config.get("text")
    text = [text] if isinstance(text, str) else text
    if not isinstance(text, list) or not text or not all(_is_field(f) for f in text):
        raise ConfigurationError(
            f"{where}: 'text:' must name the output field of '{written}' to search, or a list "
            "of them, such as [summary, keywords].",
            context=context,
        )
    if len(set(text)) != len(text):
        raise ConfigurationError(f"{where}: 'text:' names a field twice.", context=context)
    settings: dict[str, Any] = {"action": source, "text": list(text)}
    for key in ("title", "id"):
        value = config.get(key)
        if value is not None and not _is_field(value):
            raise ConfigurationError(
                f"{where}: '{key}:' must name one output field of '{written}'.",
                context=context,
            )
        settings[key] = value
    return settings


def _is_field(value: Any) -> bool:
    return isinstance(value, str) and bool(_NAME.match(value))


def _refuse_corpus_kind(
    found: Any, source: str, versioned: str, workflow: _Workflow, where: str
) -> None:
    """Refuse an action whose records are not one record per input record (D20, D23)."""
    context = {"from": source}
    if not isinstance(found, dict):
        return
    spec = builtin_tool(found) or {}
    if "route" in found or spec.get("tool") == ROUTE:
        raise ConfigurationError(
            f"{where}: 'from: {source}' names a router, whose records hold only their case. "
            "Name an action of one of its branches, or the join after them.",
            context=context,
        )
    if spec.get("loop") is not None:
        raise ConfigurationError(
            f"{where}: 'from: {source}' names a loop, whose records are spread over its "
            "iterations. Name an action of one iteration, such as "
            f"{source}_iter1__{spec['loop'].get('result', '<result>')}.",
            context=context,
        )
    if "versions" in found:
        raise ConfigurationError(
            f"{where}: 'from: {source}' names "
            + (f"a version of '{versioned}'" if versioned != source else "a version group")
            + ", which fans out each record to several versions. Name the action that merges "
            "them (version_consumption).",
            context=context,
        )
    from agent_actions.config.includes import action_defaults
    from agent_actions.output.response.expander_validation import (
        inherited_routing_kind,
        is_file_granularity,
        resolved_granularity,
    )

    defaults = action_defaults(found, workflow.defaults)
    kind = inherited_routing_kind(found, defaults)
    granularity = workflow.granularities.get(source)
    if granularity is None:
        granularity, _ = resolved_granularity(kind, found, defaults)
    # A HITL action resolves to File too, yet writes one record per input record.
    if kind == "tool" and is_file_granularity(granularity):
        raise ConfigurationError(
            f"{where}: 'from: {source}' names a tool of granularity File, which may write "
            "several records for one input record, or none. Name an action with one record "
            "per input record.",
            context=context,
        )


def _corpus_methods(raw: Any, where: str) -> dict[str, float]:
    """The methods of a search of an action's records: the index kinds it builds itself."""
    from agent_actions.knowledge.methods import trigram_supported

    corpus = _CorpusBase()
    methods = _methods(raw, corpus, where)
    if KEY_METHOD in methods:
        raise ConfigurationError(
            f"{where}: method '{KEY_METHOD}' on the records of an action comes in a later "
            "version. Use keyword, all_words, phrase or fuzzy.",
            context={"method": KEY_METHOD},
        )
    if "fuzzy" in methods and not trigram_supported():
        raise ConfigurationError(
            f"{where}: method 'fuzzy' needs an SQLite that builds a trigram index, and this "
            "one does not. Use keyword, all_words or phrase.",
            context={"method": "fuzzy"},
        )
    return methods


class _CorpusBase:
    """The checks ``_methods`` makes of a base, for the records of an action."""

    name = "the action's records"
    index = ("keyword", "fuzzy")
    has_key = True


def _refuse_unknown_keys(config: Mapping[str, Any], where: str) -> None:
    on_source = sorted(str(key) for key in config if key in SOURCE_KEYS)
    if on_source:
        raise ConfigurationError(
            f"{where}: {', '.join(on_source)} is set on the knowledge base's source, not on a "
            "retrieve entry.",
            context={"unknown_keys": on_source},
        )
    unknown = sorted(str(key) for key in config if key not in ENTRY_KEYS)
    if unknown:
        raise ConfigurationError(
            f"{where}: unknown key {', '.join(unknown)}. Keys: {', '.join(ENTRY_KEYS)}.",
            context={"unknown_keys": unknown},
        )


def _methods(raw: Any, base: Any, where: str) -> dict[str, float]:
    from agent_actions.knowledge.api import INDEX_FOR_METHOD, KNOWN_METHODS

    if isinstance(raw, str):
        methods: dict[str, float] = {raw: 1.0}
    elif isinstance(raw, list) and raw and all(isinstance(m, str) for m in raw):
        if len(set(raw)) != len(raw):
            raise ConfigurationError(f"{where}: 'method:' names a method twice.")
        methods = dict.fromkeys(raw, 1.0)
    elif isinstance(raw, dict) and raw:
        methods = {}
        for method, weight in raw.items():
            if (
                not isinstance(method, str)
                or isinstance(weight, bool)
                or not isinstance(weight, int | float)
                or not weight > 0
            ):
                raise ConfigurationError(
                    f"{where}: 'method:' maps each method to a weight above 0; got "
                    f"{method!r}: {weight!r}.",
                )
            methods[method] = float(weight)
    else:
        raise ConfigurationError(
            f"{where}: 'method:' must be a method, a list of methods (equal weights), or a "
            f"mapping of methods to weights; got {raw!r}.",
        )
    known = sorted(KNOWN_METHODS)
    for method in methods:
        if method not in KNOWN_METHODS:
            raise ConfigurationError(
                f"{where}: '{method}' is no search method. Methods: {', '.join(known)}.",
                context={"method": method},
            )
    if KEY_METHOD in methods and len(methods) > 1:
        raise ConfigurationError(
            f"{where}: method '{KEY_METHOD}' finds one chunk by its exact id and cannot be "
            "combined with another method.",
        )
    if KEY_METHOD in methods and not base.has_key:
        raise ConfigurationError(
            f"{where}: method '{KEY_METHOD}' needs every source of knowledge base "
            f"'{base.name}' to set 'id:'.",
        )
    for method in methods:
        index = INDEX_FOR_METHOD[method]
        # The key index is the chunks table that every index file holds; no base declares it.
        if method != KEY_METHOD and index not in base.index:
            raise ConfigurationError(
                f"{where}: method '{method}' searches the '{index}' index, which knowledge base "
                f"'{base.name}' does not build (index: {', '.join(base.index)}). Add '{index}' "
                "to its 'index:' in agent_actions.yml.",
                context={"method": method, "index": index},
            )
    return methods


def _query(
    raw: Any,
    names: Mapping[str, str],
    graph: Mapping[str, list[str]],
    upstream: set[str],
    where: str,
) -> list[str]:
    refs = [raw] if isinstance(raw, str) else raw
    if not isinstance(refs, list) or not refs or not all(isinstance(r, str) for r in refs):
        raise ConfigurationError(
            f"{where}: 'query:' must be a field reference, or a list of them, such as "
            "source.text.",
        )
    return [_ref(ref, names, graph, upstream, f"{where}: 'query: {ref}'") for ref in refs]


def _where(
    raw: Any,
    fields: set[str] | None,
    about: str,
    searched: Sequence[str],
    names: Mapping[str, str],
    graph: Mapping[str, list[str]],
    upstream: set[str],
    where: str,
) -> dict[str, Any]:
    """The `where:` filters. *fields* are those a base allows; for a corpus (None), any
    output field outside the *searched* ``text`` fields (checked against the schema later)."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"{where}: 'where:' must map each metadata field to a value or a field reference."
        )
    filters: dict[str, Any] = {}
    for field, value in raw.items():
        allowed = (
            field in fields if fields is not None else _is_field(field) and field not in searched
        )
        if not allowed:
            listed = (", ".join(sorted(fields)) or "none") if fields is not None else None
            raise ConfigurationError(
                f"{where}: 'where:' names '{field}', which is no metadata field of {about}"
                + (f" (metadata fields: {listed})." if listed is not None else "."),
                context={"field": str(field)},
            )
        label = f"{where}: 'where: {{{field}: ...}}'"
        if isinstance(value, dict):
            if set(value) != {"value"} or isinstance(value["value"], dict | list):
                raise ConfigurationError(
                    f"{label} must be a constant, a field reference, or {{value: <constant>}}."
                )
            filters[str(field)] = {"value": value["value"]}
        elif isinstance(value, list):
            raise ConfigurationError(f"{label} must be one value, not a list.")
        elif isinstance(value, str) and _is_ref(value, names, graph):
            filters[str(field)] = _ref(value, names, graph, upstream, label)
        else:
            filters[str(field)] = {"value": value}
    return filters


def _is_ref(value: str, names: Mapping[str, str], graph: Mapping[str, list[str]]) -> bool:
    root, dot, _ = value.partition(".")
    return bool(dot) and (root == "source" or names.get(root, root) in graph)


def _ref(
    ref: str,
    names: Mapping[str, str],
    graph: Mapping[str, list[str]],
    upstream: set[str],
    where: str,
) -> str:
    parts = ref.split(".")
    if len(parts) < 2 or not all(_NAME.match(part) or part == "_" for part in parts):
        raise ConfigurationError(
            f"{where}: a field reference is written <action>.<field>, such as source.text.",
            context={"reference": ref},
        )
    root = names.get(parts[0], parts[0])
    if root != "source" and root not in upstream:
        known = "an action of the workflow" if root in graph else "no action of the workflow"
        raise ConfigurationError(
            f"{where}: '{parts[0]}' is {known} upstream of the action. A query or 'where:' "
            "reads source or an action the action depends on.",
            context={"reference": ref},
        )
    return ".".join([root, *parts[1:]])


def _whole(
    config: Mapping[str, Any],
    key: str,
    default: int | None,
    low: int,
    high: int | None,
    where: str,
) -> Any:
    value = config.get(key, default)
    if value is None and default is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < low
        or (high is not None and value > high)
    ):
        bound = f"from {low} to {high}" if high is not None else f"of at least {low}"
        raise ConfigurationError(
            f"{where}: '{key}:' must be a whole number {bound}; got {value!r}.",
            context={key: repr(value)},
        )
    return value


# -- the action --------------------------------------------------------------


def _wire_action(action: dict[str, Any], steps: dict[str, str], where: str) -> None:
    scope = dict(action["context_scope"])
    scope.pop(RETRIEVE_KEY)
    for directive in _SCOPE_LISTS:
        refs = scope.get(directive)
        if isinstance(refs, list):
            scope[directive] = [_aliased_ref(ref, steps, where) for ref in refs]
    observe = list(scope.get("observe") or [])
    for step in steps.values():
        if f"{step}.*" not in observe:
            observe.append(f"{step}.*")
    scope["observe"] = observe
    action["context_scope"] = scope
    _add_dependencies(action, list(steps.values()))
    guard = action.get("guard")
    label = f"{where}: its guard"
    if isinstance(guard, str):
        action["guard"] = _aliased(guard, steps, label)
    elif isinstance(guard, dict):
        for key in ("condition", "clause"):
            if isinstance(guard.get(key), str):
                guard[key] = _aliased(guard[key], steps, label)
    action[_STEPS_KEY] = dict(steps)


def _copy_guards(actions: list[Any]) -> None:
    """Give each step its action's guard, unless the guard reads one of the action's steps."""
    by_name = {
        a["name"]: a for a in actions if isinstance(a, dict) and isinstance(a.get("name"), str)
    }
    for step in by_name.values():
        spec = builtin_tool(step)
        if spec is None or spec["tool"] != RETRIEVE:
            continue
        action = by_name[spec["action"]]
        guard = action.get("guard")
        if guard is None:
            continue
        paths = _guard_paths(guard)
        own = set(action.get(_STEPS_KEY, {}).values())
        if paths is None or any(path.split(".", 1)[0] in own for path in paths):
            # The action evaluates the guard once the step has run for every record.
            continue
        step["guard"] = copy.deepcopy(guard)
        if action.get(SENDS_ELSEWHERE_KEY):
            step[SENDS_ELSEWHERE_KEY] = True
        roots = [path.split(".", 1)[0] for path in paths]
        _add_dependencies(step, [r for r in roots if r in by_name and r != step["name"]])
        _add_observe(
            step, [p for p in paths if p.split(".", 1)[0] in by_name or p[:7] == "source."]
        )


def _guard_paths(guard: Any) -> list[str] | None:
    """The field paths a SQL guard reads; None for a guard whose reads are not known."""
    clause = guard if isinstance(guard, str) else None
    if isinstance(guard, dict):
        clause = guard.get("clause") or guard.get("condition")
    if not isinstance(clause, str) or clause.strip().lower().startswith("udf:"):
        return None
    from agent_actions.expectations.expression import referenced_field_paths
    from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

    parsed = WhereClauseParser().parse_cached(clause)
    if not parsed.success or parsed.ast is None:
        return None
    return [path for path in referenced_field_paths(parsed.ast.root) if "." in path]


def _dependencies_of(action: Mapping[str, Any]) -> list[str]:
    dependencies = action.get("dependencies") or []
    if isinstance(dependencies, str):
        return [dependencies]
    return [d for d in dependencies if isinstance(d, str)]


def _add_dependencies(action: dict[str, Any], names: Sequence[str]) -> None:
    dependencies = _dependencies_of(action)
    added = [name for name in names if name not in dependencies]
    if added:
        action["dependencies"] = [*dependencies, *added]


def _add_observe(action: dict[str, Any], refs: Sequence[str]) -> None:
    scope = dict(action.get("context_scope") or {})
    observe = list(scope.get("observe") or [])
    scope["observe"] = [*observe, *(ref for ref in refs if ref not in observe)]
    action["context_scope"] = scope


# -- the alias ---------------------------------------------------------------


def _aliased(text: str, steps: Mapping[str, str], where: str) -> str:
    """*text* with each ``retrieve.<entry>`` outside a quoted string written as its step."""

    def alias(match: re.Match[str]) -> str:
        path, name = match.group("path"), match.group("name")
        if name == RETRIEVE_KEY:
            raise ConfigurationError(
                f"{where} reads '{RETRIEVE_KEY}' whole; read one entry, as "
                f"{RETRIEVE_KEY}.<entry>.matches.",
            )
        if path is None or not path.startswith(f"{RETRIEVE_KEY}."):
            return match.group(0)
        _, entry, *rest = path.split(".")
        if entry not in steps:
            entries = ", ".join(steps) or "none"
            raise ConfigurationError(
                f"{where} reads '{RETRIEVE_KEY}.{entry}', which is no entry of the action's "
                f"context_scope.retrieve (entries: {entries}).",
                context={"entry": entry},
            )
        return ".".join([steps[entry], *rest])

    return _TOKEN.sub(alias, text)


def _aliased_ref(ref: Any, steps: Mapping[str, str], where: str) -> Any:
    if isinstance(ref, str):
        return _aliased(ref, steps, f"{where}: context_scope") if "." in ref else ref
    if isinstance(ref, dict) and isinstance(ref.get("field"), str):
        return {**ref, "field": _aliased(ref["field"], steps, f"{where}: context_scope")}
    return ref


def _refuse_alias_without_entries(actions: list[Any], workflow_file: str) -> None:
    """Refuse ``retrieve.<entry>`` in the scope or guard of an action that has no entry."""
    for action in actions:
        if not isinstance(action, dict) or _STEPS_KEY in action or "name" not in action:
            continue
        where = f"Action '{action['name']}' in {workflow_file}"
        scope = action.get("context_scope")
        for directive in _SCOPE_LISTS:
            refs = scope.get(directive) if isinstance(scope, dict) else None
            for ref in refs if isinstance(refs, list) else []:
                _aliased_ref(ref, {}, where)
        guard = action.get("guard")
        clause = guard.get("condition") if isinstance(guard, dict) else guard
        if isinstance(clause, str) and RETRIEVE_KEY in clause:
            _aliased(clause, {}, f"{where}: its guard")


# -- the workflow ------------------------------------------------------------


def _entries_of(entry: Any) -> dict[Any, Any]:
    scope = entry.get("context_scope") if isinstance(entry, dict) else None
    raw = scope.get(RETRIEVE_KEY) if isinstance(scope, dict) else None
    if raw is None or not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
        return {}
    if not isinstance(raw, dict) or not raw:
        raise ConfigurationError(
            f"Action '{entry['name']}': context_scope.retrieve must map each entry name to "
            "its search, as help: {from: <knowledge base>, query: source.text}.",
            context={"action_name": entry["name"]},
        )
    return raw


def _refuse_in_defaults(data: dict[str, Any], workflow_file: str, project_root: Path | None):
    levels = [("'defaults:' of " + workflow_file, data.get("defaults"))]
    if any(_entries_in_scope(e) for e in data["actions"]) or _entries_in_scope(
        data.get("defaults")
    ):
        project = load_project_config(resolve_project_root(project_root))
        levels.append(
            ("'default_agent_config:' in agent_actions.yml", project.get("default_agent_config"))
        )
    for label, level in levels:
        if _entries_in_scope(level):
            raise ConfigurationError(
                f"context_scope.retrieve under {label}: a retrieve entry is set on the action "
                "that reads it, not as a default.",
            )


def _entries_in_scope(level: Any) -> bool:
    scope = level.get("context_scope") if isinstance(level, dict) else None
    return isinstance(scope, dict) and RETRIEVE_KEY in scope


def _instance_names(action: Mapping[str, Any]) -> dict[str, str]:
    from agent_actions.config.includes import instance_names

    return instance_names(action)


def _entries_by_name(entries: list[Any]) -> dict[str, dict[str, Any]]:
    """Each action, route and join entry of the workflow by its name."""
    found: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for key in ("name", "route", "join"):
            if isinstance(entry.get(key), str):
                found[entry[key]] = entry
                break
    return found


def _read_graph(entries: list[Any]) -> dict[str, list[str]]:
    """Each action, route and join entry of the workflow, mapped to the names it reads."""
    graph: dict[str, list[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("name"), str):
            dependencies = entry.get("dependencies") or []
            if isinstance(dependencies, str):
                dependencies = [dependencies]
            graph[entry["name"]] = [d for d in dependencies if isinstance(d, str)]
        elif isinstance(entry.get("route"), str):
            on = entry.get("on", entry.get(True))
            graph[entry["route"]] = [on.split(".", 1)[0]] if isinstance(on, str) else []
        elif isinstance(entry.get("join"), str):
            of = entry.get("of")
            graph[entry["join"]] = (
                [n for n in of if isinstance(n, str)] if isinstance(of, list) else []
            )
    # Each action of a route's branch runs below the router, as the route desugar makes it.
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("route"), str):
            continue
        cases = entry.get("cases")
        targets = [*(cases.values() if isinstance(cases, dict) else ()), entry.get("default")]
        for target in targets:
            for member in (
                [target] if isinstance(target, str) else target if isinstance(target, list) else []
            ):
                if isinstance(member, str) and member in graph and member != entry["route"]:
                    graph[member] = [*graph[member], entry["route"]]
    return graph


def _upstream(name: str, graph: Mapping[str, list[str]]) -> set[str]:
    found: set[str] = set()
    stack = list(graph.get(name, ()))
    while stack:
        current = stack.pop()
        if current in found or current == name:
            continue
        found.add(current)
        stack.extend(graph.get(current, ()))
    return found
