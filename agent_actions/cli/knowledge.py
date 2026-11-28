"""``agac knowledge``: list, build and search the knowledge bases of agent_actions.yml."""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project

logger = logging.getLogger(__name__)


def _bases(project_root: Path, name: str | None) -> dict[str, Any]:
    from agent_actions.knowledge.api import KnowledgeConfigError, load_knowledge_config
    from agent_actions.knowledge.config import unknown_base_message

    bases = load_knowledge_config(project_root)
    if name is None:
        return bases
    if name not in bases:
        raise KnowledgeConfigError(
            unknown_base_message(name, bases), context={"knowledge_base": name}
        )
    return {name: bases[name]}


def _kinds_entries_use(project_root: Path) -> dict[str, set[frozenset[str]]]:
    """Each base, and the sets of index kinds the retrieve entries of the workflows read.

    A workflow that does not load is left out: its own commands report why.
    """
    import jinja2
    import yaml

    from agent_actions.errors import AgentActionsError
    from agent_actions.llm.providers.tools.builtin import (
        RETRIEVE,
        builtin_tool,
        searched_indexes,
    )
    from agent_actions.prompt.render_workflow import render_pipeline_with_templates

    used: dict[str, set[frozenset[str]]] = {}
    for config in sorted(project_root.glob("agent_workflow/*/agent_config/*.y*ml")):
        try:
            rendered = render_pipeline_with_templates(
                config,
                project_root / "templates",
                compile_schemas=False,
                project_root=project_root,
            )
        except (AgentActionsError, OSError, ValueError, jinja2.TemplateError) as error:
            logger.debug("knowledge: %s does not load: %s", config, error)
            continue
        for action in (yaml.safe_load(rendered) or {}).get("actions") or []:
            spec = builtin_tool(action) if isinstance(action, dict) else None
            if spec is not None and spec["tool"] == RETRIEVE:
                base, kinds = searched_indexes(spec)
                used.setdefault(base, set()).add(kinds)
    return used


def _kinds(base: Any, used: set[frozenset[str]]) -> list[str]:
    """The index kinds a base declares, then ``key`` when an entry searches by key."""
    extra = sorted({kind for kinds in used for kind in kinds} - set(base.index))
    return [*base.index, *extra]


@click.group()
def knowledge() -> None:
    """List, build and search the knowledge bases."""


@knowledge.command("list")
@handles_user_errors("knowledge list")
@requires_project
def list_bases(project_root: Path) -> None:
    """List each knowledge base, its indexes and whether they are built.

    Reads the sources to compute each digest, and the workflows to find a `key` index an
    entry uses. Builds nothing and connects to no database.
    """
    from agent_actions.errors import ConfigurationError
    from agent_actions.knowledge.chunks import scan
    from agent_actions.knowledge.index import index_digest, index_path

    bases = _bases(project_root, None)
    if not bases:
        click.echo("No knowledge base in agent_actions.yml.")
        return
    used = _kinds_entries_use(project_root)
    for name, base in bases.items():
        click.echo(f"{name}: {len(base.sources)} source(s), index: {', '.join(base.index)}")
        try:
            found = scan(project_root, name, base, connect=False)
        except ConfigurationError as error:
            click.echo(f"  not built: {error}")
            continue
        rows = sum(len(table.rows) for table in found.tables)
        click.echo(f"  {len(found.files)} file(s), {rows} database row(s)")
        for kind in _kinds(base, used.get(name, set())):
            digest = index_digest(found.content_digest, kind)
            built = index_path(project_root, name, kind, digest).exists()
            click.echo(f"  {kind}: {digest} ({'built' if built else 'not built'})")


@knowledge.command("build")
@click.argument("name", required=False)
@click.option("--refresh", is_flag=True, help="Read each database source's query again")
@click.option(
    "--prune",
    is_flag=True,
    help="Remove the index files of earlier digests; refused while a run is in progress",
)
@handles_user_errors("knowledge build")
@requires_project
def build(project_root: Path, name: str | None, refresh: bool, prune: bool) -> None:
    """Build the indexes of each knowledge base, or of NAME.

    \b
    Examples:
        agac knowledge build
        agac knowledge build help_center --refresh --prune
    """
    from agent_actions.input.loaders.database_source import (
        forget_refresh_request,
        request_refresh,
    )
    from agent_actions.knowledge.chunks import scan
    from agent_actions.knowledge.index import build_indexes, index_path, set_path
    from agent_actions.knowledge.index import prune as prune_files

    bases = _bases(project_root, name)
    used = _kinds_entries_use(project_root)
    if refresh:
        request_refresh()
    current: dict[str, set[Path]] = {}
    try:
        for base_name, base in bases.items():
            found = scan(project_root, base_name, base, refresh=refresh)
            current[base_name] = set()
            for kind in _kinds(base, used.get(base_name, set())):
                digest, built = build_indexes(project_root, found, [kind])
                current[base_name].add(index_path(project_root, base_name, kind, digest))
                click.echo(f"{base_name} {kind}: {digest} ({'built' if built else 'up to date'})")
            # The set file of each group of kinds an entry reads; prune keeps it.
            for kinds in [frozenset(base.index), *used.get(base_name, set())]:
                if len(kinds) > 1:
                    digest, _ = build_indexes(project_root, found, kinds)
                    current[base_name].add(set_path(project_root, base_name, digest))
    finally:
        if refresh:
            forget_refresh_request()
    if prune:
        with ExitStack() as runs:
            _hold_every_run_lock(project_root, runs)
            removed = prune_files(project_root, current)
        click.echo(f"Removed {len(removed)} old index file(s).")


def _hold_every_run_lock(project_root: Path, stack: ExitStack) -> None:
    """Hold the run lock of each workflow, so no run reads a file that prune removes."""
    from agent_actions.storage.run_lock import hold_run_lock

    for lock in sorted(project_root.glob("**/agent_io/store/*.db.lock")):
        workflow = lock.name.removesuffix(".db.lock")
        stack.enter_context(hold_run_lock(lock.parent.parent, workflow))


@knowledge.command("search")
@click.argument("name")
@click.argument("text")
@click.option("-k", "top_k", type=click.IntRange(1, 50), default=5, show_default=True)
@click.option(
    "--method",
    "methods",
    multiple=True,
    help="A search method; repeat it to merge methods with equal weights. Default: keyword",
)
@click.option("--json", "as_json", is_flag=True, help="Print the output a retrieve step stores")
@handles_user_errors("knowledge search")
@requires_project
def search(
    project_root: Path, name: str, text: str, top_k: int, methods: tuple[str, ...], as_json: bool
) -> None:
    """Search knowledge base NAME for TEXT, as a retrieve entry does.

    Builds the indexes it reads when they are stale.

    \b
    Examples:
        agac knowledge search help_center "charged twice"
        agac knowledge search help_center "pasword" --method fuzzy -k 3 --json
    """
    from agent_actions.knowledge.api import (
        INDEX_FOR_METHOD,
        KNOWN_METHODS,
        KnowledgeConfigError,
        ensure_indexes,
        retrieve,
    )

    base = _bases(project_root, name)[name]
    chosen = list(dict.fromkeys(methods or ("keyword",)))
    for method in chosen:
        if method not in KNOWN_METHODS:
            raise click.BadParameter(
                f"'{method}' is not a method; the methods are {', '.join(sorted(KNOWN_METHODS))}",
                param_hint="--method",
            )
        index = INDEX_FOR_METHOD[method]
        if index == "key" and not base.has_key:
            raise KnowledgeConfigError(
                f"knowledge base '{name}': method 'key' needs 'id:' on every source"
            )
        if index != "key" and index not in base.index:
            raise KnowledgeConfigError(
                f"knowledge base '{name}': method '{method}' reads the {index} index, which "
                f"the base does not declare. Add {index} to its 'index:' list"
            )
    if "key" in chosen and len(chosen) > 1:
        raise click.BadParameter(
            "'key' cannot be combined with other methods", param_hint="--method"
        )
    digest = ensure_indexes(
        project_root, name, {INDEX_FOR_METHOD[m] for m in chosen}, sandbox=False
    )
    result = retrieve(
        project_root,
        base=name,
        digest=digest,
        methods=dict.fromkeys(chosen, 1.0),
        query_text=text,
        where={},
        top_k=top_k,
        candidates=max(20, 4 * top_k),
        max_context_tokens=None,
        max_per_origin=None,
    )
    if as_json:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return
    click.echo(f"query: {result['query']}  index: {result['index']}  count: {result['count']}")
    for match in result["matches"]:
        click.echo(f"{match['rank']}. {match['id']}  score {match['score']:.4f}  {match['title']}")
        preview = " ".join(match["text"].split())
        click.echo(f"   {preview[:160]}{'...' if len(preview) > 160 else ''}")
