"""LSP diagnostic publishing and collection logic."""

from pathlib import Path

from lsprotocol import types as lsp

from agent_actions.record.envelope import RECORD_FRAMEWORK_FIELDS

# The evaluator promotes every record key EXCEPT `content`, whose namespaces it spreads
# instead. So `content == 'x'` resolves against nothing and filters every record -- the
# one member of the set that must stay reportable.
_PROMOTED_RECORD_FIELDS = RECORD_FRAMEWORK_FIELDS - {"content"}
from agent_actions.utils.constants import RUNTIME_BUS_NAMESPACES, SPECIAL_NAMESPACES

from .models import Location, ProjectIndex, ReferenceType
from .resolver import resolve_reference


def publish_diagnostics(uri: str, *, get_index_for_file, get_text_document, publish_fn) -> None:
    """Publish diagnostics for a file.

    Args:
        uri: Document URI.
        get_index_for_file: Callable(Path) -> ProjectIndex | None.
        get_text_document: Callable(uri) -> TextDocument | None.
        publish_fn: Callable(PublishDiagnosticsParams) -> None.
    """
    from .utils import uri_to_path

    file_path = uri_to_path(uri)
    index = get_index_for_file(file_path)
    if not index:
        return

    doc = get_text_document(uri)
    if not doc:
        return

    diagnostics = collect_diagnostics(file_path, index)
    publish_fn(lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics))


def collect_diagnostics(file_path: Path, index: ProjectIndex) -> list[lsp.Diagnostic]:
    """Collect diagnostics for missing references and workflow issues."""
    diagnostics: list[lsp.Diagnostic] = []
    references = index.references_by_file.get(file_path, [])
    actions = index.file_actions.get(file_path, {})

    for reference in references:
        if reference.type in {
            ReferenceType.PROMPT,
            ReferenceType.TOOL,
            ReferenceType.SCHEMA,
            ReferenceType.ACTION,
            ReferenceType.WORKFLOW,
            ReferenceType.SEED_FILE,
        }:
            resolved = resolve_reference(reference, index, file_path)
            if not resolved:
                diagnostics.append(
                    _build_diagnostic(
                        reference.location,
                        f"Unresolved {reference.type.value} reference `{reference.value}`.",
                        lsp.DiagnosticSeverity.Error,
                    )
                )

        if reference.type == ReferenceType.CONTEXT_FIELD:
            action_name, field = _split_context_reference(reference.value)

            # Skip validation for special namespaces (source, loop, workflow, seed, etc.)
            # These are built-in data sources, not user-defined actions
            if action_name in SPECIAL_NAMESPACES:
                continue

            action_location = index.get_action(action_name, file_path)
            if not action_location and _resolve_upstream(index, file_path, action_name):
                # A version variant: the base declares `versions:`, and the run writes this
                # name. get_action only knows declared names, which is why the framework's
                # own examples carry three of these Errors each.
                continue
            if not action_location:
                diagnostics.append(
                    _build_diagnostic(
                        reference.location,
                        f"Cannot resolve `{reference.value}` — action "
                        f"`{action_name}` is not defined in this workflow.",
                        lsp.DiagnosticSeverity.Error,
                    )
                )
                continue

            # Skip field validation for wildcard pattern (action.*)
            # The * means "all fields from this action's output"
            if field and field != "*":
                schema_fields = _get_action_schema_fields(index, file_path, action_name)
                if schema_fields and field not in schema_fields:
                    diagnostics.append(
                        _build_diagnostic(
                            reference.location,
                            f"Cannot resolve `{reference.value}` — action "
                            f"`{action_name}` has no output field `{field}`.",
                            lsp.DiagnosticSeverity.Error,
                        )
                    )

    duplicates = index.duplicate_actions_by_file.get(file_path, set())
    if duplicates:
        for action_name in sorted(duplicates):
            action_meta = actions.get(action_name)
            if not action_meta:
                continue
            diagnostics.append(
                _build_diagnostic(
                    action_meta.location,
                    f"Duplicate action name `{action_name}` defined in this workflow.",
                    lsp.DiagnosticSeverity.Warning,
                )
            )

    for action in actions.values():
        if action.guard_condition and action.guard_variables:
            for variable in action.guard_variables:
                if _guard_is_unresolvable(action, index, file_path, variable):
                    if "." in variable:
                        namespace = variable.split(".", 1)[0]
                        variants = _version_variants(index, file_path, namespace)
                        if variants:
                            # Naming `{namespace}_1` would misdirect on a named range:
                            # `range: [fast, slow]` is stored as `base_fast`, and an author
                            # following that advice writes a clause that filters everything.
                            shown = ", ".join(f"`{name}`" for name in variants[:3])
                            message = (
                                f"Guard condition references `{variable}`, but `{namespace}` "
                                f"declares versions and is stored per variant ({shown}), "
                                "never under its own name."
                            )
                        else:
                            # The test is workflow-wide, so "add it as an upstream" is not the
                            # remedy, and the namespace may not exist at all -- saying it
                            # "does not produce" the field implies it does exist.
                            message = (
                                f"Guard condition references `{variable}`, and no action in "
                                f"this workflow produces `{namespace}`."
                            )
                    else:
                        message = (
                            f"Guard condition references `{variable}` without an action "
                            "prefix, which resolves against no upstream namespace."
                        )
                        matches = _dotted_suggestions(action, index, file_path, variable)
                        if matches:
                            message += f" Did you mean {', '.join(f'`{m}`' for m in matches)}?"
                    diagnostics.append(
                        _build_diagnostic(
                            Location(
                                file_path=file_path,
                                line=action.guard_line or action.location.line,
                                column=0,
                            ),
                            message,
                            lsp.DiagnosticSeverity.Warning,
                        )
                    )
        if len(set(action.versions_params)) != len(action.versions_params):
            diagnostics.append(
                _build_diagnostic(
                    Location(
                        file_path=file_path,
                        line=action.versions_line or action.location.line,
                        column=0,
                    ),
                    "Duplicate versions.param entries detected.",
                    lsp.DiagnosticSeverity.Warning,
                )
            )

    return diagnostics


def collect_available_guard_variables(file_path: Path, index: ProjectIndex) -> set[str]:
    """Collect all guard-referenceable variables across all actions in a file.

    Used by completions and signature help, where cursor-to-action mapping is not
    available. Diagnostics judge each clause against its own action instead.
    """
    actions = index.file_actions.get(file_path, {})
    variables: set[str] = set()
    for action in actions.values():
        for observed in action.context_observe:
            variables.add(observed)
        for passthrough in action.context_passthrough:
            variables.add(passthrough)
        if action.schema_ref:
            schema = index.get_schema_definition(action.schema_ref)
            if schema:
                for field in schema.fields:
                    variables.add(f"{action.name}.{field}")
    return variables


# What a versioned guard resolves bare: VersionNamespaceBuilder promotes i/idx plus every
# _version_context key outside its reserved set (so base_name/param_name too; length, first
# and last stay under `version`). Unconditional -- a rendered workflow has `versions:` stripped.
_VERSION_KEYS = frozenset({"i", "idx", "base_name", "param_name"})


def _named_upstreams(action) -> set[str]:
    """Actions this one names, by dependency or by a context_scope reference.

    `dependencies:` alone is not the set: an action can reach an upstream through
    context_scope and have the dependency inferred, so treating an empty list as
    "first-stage" mistakes an ordinary action for one reading the staging row.
    """
    named = set(action.dependencies)
    for ref in (*action.context_observe, *action.context_passthrough, *action.context_drop):
        if "." in ref:
            namespace = ref.split(".", 1)[0]
            if namespace not in RUNTIME_BUS_NAMESPACES:
                named.add(namespace)
    return named


def _guard_is_unresolvable(action, index: ProjectIndex, file_path: Path, variable: str) -> bool:
    """Whether *variable* provably resolves against nothing a guard can read.

    A guard reads the record as stored, so `context_scope` plays no part. Only a reference
    this function can prove wrong is reported; everything it cannot settle is left alone,
    because the alternative is warning about clauses the runtime answers.
    """
    namespace, dot, _field = variable.partition(".")

    if not dot:
        # A bare name resolves through three promotions, so it is only wrong when none of
        # them can apply. output_field and the version param are declared in this file; a
        # first-stage action's staging columns are not knowable from it at all.
        if variable in _VERSION_KEYS or variable in set(action.versions_params):
            return False
        if variable in _PROMOTED_RECORD_FIELDS:
            # Measured: `source_guid == 'x'` evaluates true against a record carrying it.
            return False
        if variable in RUNTIME_BUS_NAMESPACES:
            # `source IS NOT NULL` names the namespace itself. _build_evaluation_context puts
            # it at top level, so the clause resolves -- the dotted branch below already
            # exempts these and returning before it reached them was the inconsistency.
            return False
        upstreams = _named_upstreams(action)
        if variable in upstreams:
            # Likewise an upstream's own namespace name: `assess IS NOT NULL` resolves,
            # because every dependency namespace is promoted to top level too.
            return False
        if not upstreams:
            # No upstream named at all: a first-stage action, whose content is the staging
            # row. Its columns are not knowable from this file, so nothing here is provable.
            return False
        for dep_name in upstreams:
            dep = _resolve_upstream(index, file_path, dep_name)
            if dep is None or dep.output_field == variable or dep.spreads_output_flat:
                # A version-merge tool at FILE granularity makes its fields content's own
                # top-level keys, so any bare name may be one of them. Measured with a real
                # run: the bare clause is the one that works and the dotted one filters
                # every record -- the opposite of every other action.
                return False
        return True

    if namespace in RUNTIME_BUS_NAMESPACES or namespace in _PROMOTED_RECORD_FIELDS:
        # Record keys the evaluator copies to top level, so they resolve dotted as well as
        # bare -- and guards.md documents `metadata.reason`, batch-recovery.md documents
        # `_recovery.retry.succeeded`, so reporting them warns about the documented shape.
        return False
    for dep_name in _named_upstreams(action):
        dep = _resolve_upstream(index, file_path, dep_name)
        if dep is not None and dep.output_field == namespace:
            # guard_context promotes the output_field's VALUE, which may be an object, so
            # `payload.score` resolves just as bare `payload` does. Exempting one spelling
            # and reporting the other is the same promotion judged two ways.
            return False
    # Which fields a namespace holds is not decidable here (the record accumulates namespaces;
    # `expect` is framework-attached and banned from schemas) -- reporting them gave 19 false
    # warnings. Whether it exists is decidable, fires on nothing, and catches a misspelt action.
    return not _workflow_produces(index, file_path, namespace)


def _resolve_upstream(index: ProjectIndex, file_path: Path, name: str):
    """Action metadata for *name*, which may be a version variant rather than a declared name.

    A variant (`score_1`) is never a key in file_actions -- only its base is. Treating that
    lookup miss as "unknown upstream" switched the whole bare-name check off for every
    fan-in action, which is the shape the shipped examples teach.
    """
    meta = index.get_action_metadata(name, file_path)
    if meta is not None:
        return meta
    workflow = index.file_to_workflow.get(file_path) or index.workflow_for_file(file_path)
    for other_file, actions in index.file_actions.items():
        if workflow and index.file_to_workflow.get(other_file) != workflow:
            continue
        for other in actions.values():
            if name in other.version_variants:
                return other
    return None


def _version_variants(index: ProjectIndex, file_path: Path, namespace: str) -> list[str]:
    """The namespaces *namespace* is actually stored under, if it declares versions."""
    meta = index.get_action_metadata(namespace, file_path)
    return list(meta.version_variants) if meta else []


def _workflow_produces(index: ProjectIndex, file_path: Path, namespace: str) -> bool:
    """Whether any action in this workflow writes *namespace*, expansions included.

    A versions block expands before execution, so the action's own declared name is NOT one
    of them -- the run writes `base_1`, `base_2`, ... and a guard gets no base-name expansion
    (context_scope does, in scope_inference, which is why only it can name a base). Confirmed
    against a real store: `target_data.action_name` holds `extract_raw_qa_1/2/3` and never
    `extract_raw_qa`. The variants come from the shared expander rule so this cannot drift
    from what the run actually produces.
    """
    meta = index.get_action_metadata(namespace, file_path)
    if meta is not None and meta.spreads_output_flat:
        # Its output is spread flat, so this name is NOT a namespace at runtime. The clause
        # is wrong, but saying so would also be saying the fix is to add a prefix, which is
        # what breaks it -- stay silent rather than name the wrong remedy.
        return True
    if meta is not None and not meta.version_variants:
        return True
    # get_action_metadata searches the whole workflow, so the variant sweep must too:
    # scoping it to one file reported a dependency that resolves in a sibling file as
    # "does not produce", contradicting the resolved reference in the same pass.
    workflow = index.file_to_workflow.get(file_path) or index.workflow_for_file(file_path)
    for other_file, actions in index.file_actions.items():
        if workflow and index.file_to_workflow.get(other_file) != workflow:
            continue
        if any(namespace in other.version_variants for other in actions.values()):
            return True
    return False


def _dotted_suggestions(action, index: ProjectIndex, file_path: Path, field: str) -> list[str]:
    """Dotted spellings of a bare *field*, from this action's upstream schemas."""
    matches = set()
    for dep_name in _named_upstreams(action):
        if field in _get_action_schema_fields(index, file_path, dep_name):
            matches.add(f"{dep_name}.{field}")
    for ref in (*action.context_observe, *action.context_passthrough):
        if "." in ref and ref.rsplit(".", 1)[1] == field:
            matches.add(ref)
    return sorted(matches)


def _build_diagnostic(
    location: Location, message: str, severity: lsp.DiagnosticSeverity
) -> lsp.Diagnostic:
    """Build an LSP diagnostic from a location."""
    return lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=location.line, character=location.column),
            end=lsp.Position(
                line=location.end_line or location.line,
                character=location.end_column or location.column + 1,
            ),
        ),
        message=message,
        severity=severity,
    )


def _split_context_reference(value: str) -> tuple[str, str | None]:
    """Split context reference into action name and field."""
    if "." in value:
        action_name, field = value.split(".", 1)
        return action_name, field
    return value, None


def _get_action_schema_fields(index: ProjectIndex, file_path: Path, action_name: str) -> list[str]:
    """Get fields for an action's schema."""
    action_meta = index.get_action_metadata(action_name, file_path)
    if not action_meta or not action_meta.schema_ref:
        return []
    schema = index.get_schema_definition(action_meta.schema_ref)
    if not schema:
        return []
    return schema.fields
