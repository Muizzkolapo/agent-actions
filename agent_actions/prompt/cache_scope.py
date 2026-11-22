"""Whether a call's prompt and tools are the same for every record, so a prompt-cache mark on them can be read.

Each check fails closed: what it cannot prove the same for every record counts as differing,
because a mark on text that differs writes a cache entry on every request and is never read.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, meta, nodes

from agent_actions.config.path_config import resolve_seed_file, seed_search_folders
from agent_actions.output.response.dispatch_injection import dispatch_calls_in
from agent_actions.output.response.loader import SchemaLoader
from agent_actions.prompt.cache_point import (
    CACHE_POINT_TAG_PATTERN,
    PROMPT_EXTENSIONS,
    is_cache_point,
)
from agent_actions.prompt.context.scope_application import FRAMEWORK_NAMESPACES
from agent_actions.prompt.context.scope_builder import VersionNamespaceBuilder
from agent_actions.prompt.context.seed_entry import parse_seed_entry
from agent_actions.prompt.formatter import PromptFormatter
from agent_actions.utils.constants import SCHEMA_KEY, SCHEMA_NAME_KEY
from agent_actions.utils.template_escape import escape_jinja_in_inline_code

_DISPATCH_START = re.compile(r"dispatch_task\s*\(")
_CACHE_POINT_TAG = CACHE_POINT_TAG_PATTERN

REQUEST_VARIES_PER_RECORD_KEY = "_request_varies_per_record"
"""Set on one call's config when its prompt is not the action's rendered prompt: a repair
call whose prompt does not begin with it, a judge call, or a call with the schema its record
chose."""

SHARED_PROMPT_LEN_KEY = "_shared_prompt_len"
"""Set on a repair call's config, and carried on a batch repair row: the length of the
leading part of its prompt that is the action's rendered prompt. The record's feedback
follows it, so a cache mark can sit only at its end."""

CACHE_POINTS_KEY = "_cache_points"
"""Set on one call's config, and carried on a batch row: the length of the rendered prompt
before each `{% cache_point %}` its render reached."""


def cache_points_of(call: Mapping[str, Any]) -> tuple[int, ...]:
    """The cache points of a call's config or batch row that its request may mark.

    None where the call's prompt is not the action's rendered prompt or its tools are
    the record's own: the points were measured on that prompt, after the action's tools.
    """
    if call.get(REQUEST_VARIES_PER_RECORD_KEY):
        return ()
    return tuple(call.get(CACHE_POINTS_KEY) or ())


def repair_call_scope(prompt: str, rendered_prompt: str) -> dict[str, Any]:
    """The config keys that tell a repair call's client which part of *prompt* every record shares.

    Only a prompt that begins with the rendered prompt shares that part; any other shares
    nothing a cache mark can prove.
    """
    if rendered_prompt and prompt.startswith(rendered_prompt):
        return {SHARED_PROMPT_LEN_KEY: len(rendered_prompt)}
    return {REQUEST_VARIES_PER_RECORD_KEY: True}


def record_reads_in_prompt(agent_config: Mapping[str, Any]) -> tuple[str, ...]:
    """What the action's prompt template reads that can differ from one record to the next.

    An unbound name counts unless it is ``version``, ``workflow``, ``loop``, a version
    param, or ``seed``; a ``seed`` read counts only while a seed key has ``select_by``
    and the read is not through a constant key without one. A ``dispatch_task(...)``
    call, ``random`` and ``lipsum`` count. A ``seed`` or version read also counts when
    its file or value holds a ``dispatch_task(`` call (or a seed file cannot be read),
    because the run resolves those calls on the rendered prompt, per record.
    """
    template = PromptFormatter.get_raw_prompt(agent_config)
    if not template:
        return ()
    version_context = agent_config.get("_version_context")
    version_names = frozenset(
        {"version"}
        | VersionNamespaceBuilder.promoted_names(
            version_context if isinstance(version_context, dict) else None
        )
    )
    seed_keys, per_record_keys = _seed_keys(agent_config)
    reads = _template_record_reads(
        template,
        frozenset((FRAMEWORK_NAMESPACES - {"seed"}) | version_names),
        seed_keys,
        per_record_keys,
    )
    if reads:
        return reads
    unbound = _unbound_names(template)
    seed_reason = _seed_file_dispatch_reason(agent_config) if "seed" in unbound else None
    if seed_reason:
        reads += (seed_reason,)
    if unbound & version_names and any(_dispatch_calls(version_context)):
        reads += ("version (a version value calls dispatch_task)",)
    return reads


def schema_dispatches(agent_config: Mapping[str, Any]) -> tuple[str, ...]:
    """The ``dispatch_task(...)`` calls in the action's schema; each can give a record its own tools."""
    schema = agent_config.get(SCHEMA_KEY)
    if schema is None and agent_config.get(SCHEMA_NAME_KEY):
        project_root = agent_config.get("_project_root")
        schema = SchemaLoader.load_schema(
            agent_config[SCHEMA_NAME_KEY], project_root=Path(project_root) if project_root else None
        )
    return tuple(dict.fromkeys(f"dispatch_task('{name}')" for name in _dispatch_calls(schema)))


@dataclass(frozen=True)
class CachePointUse:
    """The `{% cache_point %}` tags of an action's prompt template, and what is read before the last."""

    count: int = 0
    repeats: bool = False
    """A tag sits in a loop, a macro, a call block or a block that captures its text, where
    it can render more than once or be changed by a filter."""
    changing: tuple[str, ...] = ()
    """Read before the last tag and different on every render: no later request reads its entry."""
    per_record: tuple[str, ...] = ()
    """Read before the last tag and not `source` or data every record shares: an upstream
    action's field or a per-record seed, which records of one source may or may not share."""


def cache_point_use(agent_config: Mapping[str, Any]) -> CachePointUse:
    """How the action's prompt template uses `{% cache_point %}`."""
    template = PromptFormatter.get_raw_prompt(agent_config)
    if not template or not any(is_cache_point(node) for node in _in_order(_parse(template))):
        return CachePointUse()
    version_context = agent_config.get("_version_context")
    version_names = {"version"} | VersionNamespaceBuilder.promoted_names(
        version_context if isinstance(version_context, dict) else None
    )
    seed_keys, per_record_keys = _seed_keys(agent_config)
    return _cache_point_use(
        template,
        frozenset((FRAMEWORK_NAMESPACES - {"seed"}) | version_names | {"source"}),
        seed_keys,
        per_record_keys,
    )


def prompt_is_shared(agent_config: Mapping[str, Any]) -> bool:
    """Whether every record of this call is sent the same tools and prompt text."""
    return (
        not agent_config.get(REQUEST_VARIES_PER_RECORD_KEY)
        and not schema_dispatches(agent_config)
        and not record_reads_in_prompt(agent_config)
    )


def _seed_keys(agent_config: Mapping[str, Any]) -> tuple[frozenset[str], frozenset[str]]:
    context_scope = agent_config.get("context_scope")
    seed = context_scope.get("seed") if isinstance(context_scope, Mapping) else None
    if not isinstance(seed, Mapping):
        return frozenset(), frozenset()
    per_record = frozenset(
        key for key, entry in seed.items() if isinstance(entry, Mapping) and "select_by" in entry
    )
    return frozenset(seed), per_record


def _seed_file_dispatch_reason(agent_config: Mapping[str, Any]) -> str | None:
    """Why a file the action's seed can load may put a ``dispatch_task(`` call in the prompt.

    A file that cannot be found or read may hold one, so it is a reason too.
    """
    context_scope = agent_config.get("context_scope")
    seed = context_scope.get("seed") if isinstance(context_scope, Mapping) else None
    if not isinstance(seed, Mapping):
        return None
    folders = seed_search_folders(agent_config.get("workflow_config_path"))
    action_name = str(agent_config.get("name", ""))
    for key, raw in seed.items():
        for spec in parse_seed_entry(key, raw, action_name).file_specs():
            try:
                path = resolve_seed_file(spec, folders).path
                stat = path.stat()
                if _file_calls_dispatch(str(path), stat.st_mtime_ns, stat.st_size):
                    return f"seed.{key} (its file calls dispatch_task)"
            except (OSError, ValueError) as exc:
                return f"seed.{key} (its file could not be read: {exc})"
    return None


@lru_cache(maxsize=256)
def _file_calls_dispatch(path: str, _mtime_ns: int, _size: int) -> bool:
    return (
        _DISPATCH_START.search(Path(path).read_text(encoding="utf-8", errors="replace")) is not None
    )


def _dispatch_calls(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield from dispatch_calls_in(value)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _dispatch_calls(key)
            yield from _dispatch_calls(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _dispatch_calls(item)


def _chains(ast: nodes.Template) -> Iterator[tuple[nodes.Name, str, str | None]]:
    """Each outermost attribute or subscript chain on a name: its root, its path, its first key.

    The first key is None when it is not a constant.
    """
    accesses = [
        node
        for node in ast.find_all((nodes.Getattr, nodes.Getitem))
        if isinstance(node, nodes.Getattr | nodes.Getitem)
    ]
    inner = {
        id(node.node) for node in accesses if isinstance(node.node, nodes.Getattr | nodes.Getitem)
    }
    for node in accesses:
        if id(node) in inner:
            continue
        steps: list[tuple[str, str | None]] = []
        current: nodes.Node = node
        while isinstance(current, nodes.Getattr | nodes.Getitem):
            if isinstance(current, nodes.Getattr):
                steps.append((f".{current.attr}", current.attr))
            elif isinstance(current.arg, nodes.Const) and isinstance(current.arg.value, str | int):
                steps.append((f"[{current.arg.value!r}]".replace("'", '"'), str(current.arg.value)))
            else:
                steps.append(("[*]", None))
            current = current.node
        if isinstance(current, nodes.Name):
            steps.reverse()
            yield current, current.name + "".join(text for text, _ in steps), steps[0][1]


@lru_cache(maxsize=256)
def _parse(template: str) -> nodes.Template:
    return Environment(extensions=PROMPT_EXTENSIONS).parse(escape_jinja_in_inline_code(template))  # nosec B701  # prompt text, not HTML


def _unbound_names(template: str) -> set[str]:
    return meta.find_undeclared_variables(_parse(template))


def _in_order(ast: nodes.Node) -> list[nodes.Node]:
    return list(ast.find_all(nodes.Node))


_CHANGING = ("| random", "lipsum()")


@lru_cache(maxsize=256)
def _template_record_reads(
    template: str,
    static_names: frozenset[str],
    seed_keys: frozenset[str],
    per_record_seed_keys: frozenset[str],
) -> tuple[str, ...]:
    reads = _reads(_parse(template), None, static_names, seed_keys, per_record_seed_keys)
    reads.update(f"dispatch_task('{name}')" for name in dispatch_calls_in(template))
    return tuple(sorted(reads))


@lru_cache(maxsize=256)
def _cache_point_use(
    template: str,
    shared_names: frozenset[str],
    seed_keys: frozenset[str],
    per_record_seed_keys: frozenset[str],
) -> CachePointUse:
    ast = _parse(template)
    order = _in_order(ast)
    points = [index for index, node in enumerate(order) if is_cache_point(node)]
    repeating = (nodes.For, nodes.Macro, nodes.CallBlock, nodes.FilterBlock, nodes.AssignBlock)
    repeats = any(
        is_cache_point(node) for block in ast.find_all(repeating) for node in _in_order(block)
    )
    before = {id(node) for node in order[: points[-1]]}
    reads = _reads(ast, before, shared_names, seed_keys, per_record_seed_keys)
    changing = {read for read in reads if read in _CHANGING}
    # A dispatch_task call is text until the run resolves it, so its place is the text's.
    last_tag = max((match.end() for match in _CACHE_POINT_TAG.finditer(template)), default=0)
    changing.update(f"dispatch_task('{name}')" for name in dispatch_calls_in(template[:last_tag]))
    return CachePointUse(
        count=len(points),
        repeats=repeats,
        changing=tuple(sorted(changing)),
        per_record=tuple(sorted(reads - changing)),
    )


def _reads(
    ast: nodes.Template,
    within: set[int] | None,
    static_names: frozenset[str],
    seed_keys: frozenset[str],
    per_record_seed_keys: frozenset[str],
) -> set[str]:
    """What *ast* reads that is not a static name; only at the nodes *within*, when given."""

    def counted(node: nodes.Node) -> bool:
        return within is None or id(node) in within

    unbound = meta.find_undeclared_variables(ast)
    record_roots = unbound - static_names - {"seed"}
    seed_varies = "seed" in unbound and bool(per_record_seed_keys)

    reads: set[str] = set()
    chained: set[int] = set()
    for root, path, key in _chains(ast):
        chained.add(id(root))
        if not counted(root):
            continue
        if root.name in record_roots or (
            root.name == "seed"
            and seed_varies
            and (key not in seed_keys or key in per_record_seed_keys)
        ):
            reads.add(path)
    for name in ast.find_all(nodes.Name):
        if name.ctx != "load" or id(name) in chained or not counted(name):
            continue
        if name.name in record_roots or (name.name == "seed" and seed_varies):
            reads.add(name.name)
    if any(f.name == "random" and counted(f) for f in ast.find_all(nodes.Filter)):
        reads.add("| random")
    if any(n.name == "lipsum" and n.ctx == "load" and counted(n) for n in ast.find_all(nodes.Name)):
        reads.add("lipsum()")
    return reads
