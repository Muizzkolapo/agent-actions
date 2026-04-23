"""LSP diagnostic publishing and collection logic."""

from pathlib import Path

from lsprotocol import types as lsp

from agent_actions.utils.constants import SPECIAL_NAMESPACES

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
            if not action_location:
                diagnostics.append(
                    _build_diagnostic(
                        reference.location,
                        f"context_scope reference `{reference.value}` cannot be resolved because "
                        f"action `{action_name}` is missing.",
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
                            f"context_scope reference `{reference.value}` cannot be resolved because "
                            f"`{action_name}` output schema does not declare `{field}`.",
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
            available = _action_guard_variables(action, index)
            for variable in action.guard_variables:
                if variable not in available:
                    message = (
                        f"Guard condition references `{variable}` which is not observed "
                        "in context_scope."
                    )
                    # Suggest dotted paths if the bare field matches a namespace suffix
                    if "." not in variable:
                        matches = sorted(
                            v for v in available if "." in v and v.rsplit(".", 1)[1] == variable
                        )
                        if matches:
                            suggestion = ", ".join(f"`{m}`" for m in matches)
                            message += f" Did you mean {suggestion}?"
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

    Used by completions and signature help where cursor-to-action mapping
    is not available. For per-action diagnostic validation, use
    ``_action_guard_variables`` instead.
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


def _action_guard_variables(action, index: ProjectIndex) -> set[str]:
    """Variables available to a specific action's guard condition.

    An action's guard runs before the action, so it can only see what
    that action declares in its own context_scope (observe + passthrough).
    """
    variables: set[str] = set()
    for observed in action.context_observe:
        variables.add(observed)
    for passthrough in action.context_passthrough:
        variables.add(passthrough)
    return variables


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
