"""Staging record checks that run before any record is prepared or sent."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigValidationError
from agent_actions.prompt.context.seed_entry import SeedSelectionError, selected_seed_entries
from agent_actions.utils.constants import SPECIAL_NAMESPACES

logger = logging.getLogger(__name__)


def validate_seed_selectors(
    records: list[Any], file_path: str, action_configs: Mapping[str, Mapping[str, Any]]
) -> None:
    """Refuse a staged file with a record that no file of a selected seed covers.

    ``records`` are the first-stage rows as the run prepared them, read through
    the same source resolution a prompt uses. Every record and every action of
    the workflow is checked before any record is sent, so a bad value stops the
    run instead of surfacing from the first action that renders the record.
    """
    entries = selected_seed_entries(action_configs)
    if not entries:
        return

    from agent_actions.processing.source_resolution import resolve_first_stage_source
    from agent_actions.prompt.context.scope_builder import SourceNamespaceBuilder

    where = f"{Path(file_path).parent.name}/{Path(file_path).name}"
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        source = SourceNamespaceBuilder.fields(resolve_first_stage_source(record))
        for action_name, entry in entries:
            try:
                entry.file_for(source, action_name)
            except SeedSelectionError as exc:
                raise ConfigValidationError(
                    f"{exc} ({where}, record {index})",
                    context={
                        "file_path": file_path,
                        "record_index": index,
                        "action_name": action_name,
                        "seed_key": entry.key,
                        "select_by": entry.select_by,
                    },
                    cause=exc,
                ) from exc


# A read of a field no record holds fails every record here...
_READS_EVERY_RECORD_NEEDS = {
    "context_scope.observe": "observes",
    "prompt": "reads in its prompt",
}
# ...and here may not: a passthrough leaves the field out, as for a first action, a
# guard can test for it (`IS NULL` passes a record without it), and a prompt can read
# it under an `if`, a `default` or `.get()`.
_READS_A_RECORD_MAY_LACK = {
    "context_scope.passthrough": "passes through",
    "guard": "guards on",
    "guard.field": "guards on",
    "prompt.conditional": "reads conditionally in its prompt",
}


def validate_source_reads_below(
    records: list[Any],
    file_path: str,
    first_action: str,
    action_configs: Mapping[str, Mapping[str, Any]],
    *,
    conclusive: Callable[[], bool],
    hint: str | None = None,
) -> None:
    """Refuse an action below *first_action* reading a `source` field no staged record holds.

    Below the first stage a record's `source` is the row staged for it, which no action
    adds to, so these records are every `source` the actions below can read from this
    file. When they are not *conclusive* (other staged files may hold the field; asked
    only once a read is missing), when the read may not fail a record, or when the
    action's own guard reads the field first, the read is logged as a warning instead.
    """
    if not records:
        return

    from agent_actions.processing.source_resolution import resolve_first_stage_source
    from agent_actions.prompt.context.scope_builder import SourceNamespaceBuilder

    held: set[str] = set()
    for record in records:
        if isinstance(record, Mapping):
            held |= SourceNamespaceBuilder.fields(resolve_first_stage_source(record)).keys()

    where = f"{Path(file_path).parent.name}/{Path(file_path).name}"
    refusals: list[str] = []
    answer: list[bool] = []

    def rows_are_conclusive() -> bool:
        if not answer:
            answer.append(conclusive())
        return answer[0]

    for action_name in _actions_below(first_action, action_configs):
        reads = _source_reads(action_configs[action_name])
        # The guard runs first and decides what a record without the field does.
        guarded = {field for location, field in reads if location.startswith("guard")}
        for location, field in reads:
            if field in held:
                continue
            verb = _READS_EVERY_RECORD_NEEDS.get(location) or _READS_A_RECORD_MAY_LACK[location]
            message = (
                f"Action '{action_name}' {verb} source.{field}, but no record staged from "
                f"{where} holds '{field}'"
            )
            if (
                location in _READS_EVERY_RECORD_NEEDS
                and field not in guarded
                and rows_are_conclusive()
            ):
                refusals.append(message)
            else:
                logger.warning("%s. Records from that file will not have it.", message)

    if refusals:
        held_note = f"Its records hold: {', '.join(sorted(held))}." if held else ""
        raise ConfigValidationError(
            ". ".join(dict.fromkeys(refusals)) + ". " + (hint or held_note),
            context={"file_path": file_path, "fields_held": sorted(held)},
        )


def _actions_below(first_action: str, action_configs: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """The actions that depend on *first_action*, directly or through others.

    A version merge names the versions it merges by their base name.
    """
    below: list[str] = []
    reached = {first_action}
    names_reached = {first_action}
    grew = True
    while grew:
        grew = False
        for name, config in action_configs.items():
            dependencies = (config or {}).get("dependencies") or []
            if name in reached or not isinstance(dependencies, list):
                continue
            if names_reached.intersection(d for d in dependencies if isinstance(d, str)):
                reached.add(name)
                names_reached.update({name, (config or {}).get("version_base_name") or name})
                below.append(name)
                grew = True
    return below


def _source_reads(config: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The `source` fields *config* reads, by where, each named by its top-level key."""
    from jinja2.exceptions import TemplateSyntaxError

    from agent_actions.validation.preflight.resolution_service import (
        WorkflowResolutionService,
    )
    from agent_actions.validation.static_analyzer.reference_extractor import (
        ReferenceExtractor,
    )

    resolved = WorkflowResolutionService._resolve_prompt_for_extraction(dict(config))
    try:
        requirements = ReferenceExtractor().extract_from_agent(resolved)
    except TemplateSyntaxError:
        return []  # Pre-flight reports the template.
    prompt = resolved.get("prompt")
    always = _source_fields_every_render_reads(prompt) if isinstance(prompt, str) else set()
    reads: list[tuple[str, str]] = []
    for requirement in requirements:
        field = requirement.field_path.split(".", 1)[0]
        if requirement.source_agent != "source" or not field or "*" in field:
            continue
        location = requirement.location
        if location == "prompt" and field not in always:
            location = "prompt.conditional"
        if location in _READS_EVERY_RECORD_NEEDS.keys() | _READS_A_RECORD_MAY_LACK:
            reads.append((location, field))
    return list(dict.fromkeys(reads))


def _source_fields_every_render_reads(template: str) -> set[str]:
    """The `source` fields every render of *template* reads, whatever the record holds.

    Not one read only under an `if` or in a loop's body, on the right of `and`/`or`, bound
    by `set` or `with` (read lazily, where the name is used), nor one hedged by a
    `default`, a test (`is defined`) or a conditional expression: those may not be read,
    or not fail, when the field is missing. An `if`'s own test and a loop's iterable are.
    """
    from jinja2 import Environment, nodes
    from jinja2.exceptions import TemplateSyntaxError

    from agent_actions.utils.template_escape import escape_jinja_in_inline_code
    from agent_actions.validation.prompt_required_field_validator import _chain_root_and_field

    try:
        ast = Environment().parse(escape_jinja_in_inline_code(template))
    except TemplateSyntaxError:
        return set()

    read: set[str] = set()

    def walk(node: nodes.Node, conditional: bool) -> None:
        if isinstance(node, nodes.If | nodes.For):
            walk(node.test if isinstance(node, nodes.If) else node.iter, conditional)
            for child in [*node.body, *node.else_, *getattr(node, "elif_", [])]:
                walk(child, True)
            return
        if isinstance(node, nodes.And | nodes.Or):
            walk(node.left, conditional)
            walk(node.right, True)  # Short-circuited by the left operand.
            return
        if isinstance(node, nodes.With):
            # Like `set`, a read bound to a name is evaluated lazily, where the name is used.
            for child in node.body:
                walk(child, conditional)
            return
        if isinstance(node, nodes.Macro | nodes.CondExpr | nodes.Test | nodes.Assign):
            return
        if isinstance(node, nodes.Filter) and node.name in ("default", "d"):
            return
        if isinstance(node, nodes.Getattr | nodes.Getitem):
            ref = _chain_root_and_field(node)
            if ref is not None:
                if ref[0] == "source" and not conditional:
                    read.add(ref[1])
                return
        for child in node.iter_child_nodes():
            walk(child, conditional)

    walk(ast, False)
    return read


def validate_staging_field_names(raw_content: Any, file_path: str) -> None:
    """Validate that staging record field names do not collide with reserved namespaces.

    The framework reserves top-level names in ``SPECIAL_NAMESPACES``
    (``source``, ``version``, ``workflow``, ``seed``, ``prompt``,
    ``schema``, ``action``) as prompt-context namespaces.  If a staging
    record contains a field with one of these names the pipeline will
    silently mis-route the value at prompt-build time.

    For list inputs every dict row is checked, not just the first — staging
    files can contain heterogeneous records.
    """
    if not raw_content:
        return

    if isinstance(raw_content, dict):
        _check_dict(raw_content, file_path)
    elif isinstance(raw_content, list):
        for idx, item in enumerate(raw_content):
            if isinstance(item, dict):
                _check_dict(item, file_path)
            else:
                logger.debug(
                    "Skipping non-dict element at index %d in %s (type: %s)",
                    idx,
                    Path(file_path).name,
                    type(item).__name__,
                )


def _check_dict(record: dict[str, Any], file_path: str) -> None:
    """Raise ``ConfigValidationError`` if *record* has reserved field names."""
    collisions = SPECIAL_NAMESPACES & record.keys()
    if collisions:
        collision_list = ", ".join(sorted(collisions))
        reserved_list = ", ".join(sorted(SPECIAL_NAMESPACES))
        raise ConfigValidationError(
            f"Staging data field(s) {collision_list!r} in {Path(file_path).name} "
            f"collide with reserved namespace names.\n\n"
            f"Reserved names: {reserved_list}\n\n"
            f"Rename the colliding field(s) in your staging data "
            f"(e.g. 'source' → 'source_file', 'version' → 'doc_version').",
        )
