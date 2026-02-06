"""Agent Actions LSP Server - Main entry point."""

import logging
from pathlib import Path
from typing import Optional

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from agent_actions.utils.constants import SPECIAL_NAMESPACES

from .indexer import build_index, find_project_root
from .models import Location, ProjectIndex, ReferenceType
from .resolver import get_reference_at_position, resolve_reference
from .utils import is_in_dependencies_context, uri_to_path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SEMANTIC_TOKEN_TYPES = [
    "namespace",
    "type",
    "function",
    "variable",
    "property",
    "string",
]

SEMANTIC_TOKEN_TYPE_MAP = {
    ReferenceType.WORKFLOW: "namespace",
    ReferenceType.SCHEMA: "type",
    ReferenceType.TOOL: "function",
    ReferenceType.ACTION: "variable",
    ReferenceType.CONTEXT_FIELD: "property",
    ReferenceType.PROMPT: "string",
    ReferenceType.SEED_FILE: "string",
}


class AgentActionsLanguageServer(LanguageServer):
    """Language Server for agent-actions workflows."""

    def __init__(self):
        super().__init__("agent-actions-lsp", "v0.1.0")
        self.index: Optional[ProjectIndex] = None
        self.project_root: Optional[Path] = None


# Create server instance
server = AgentActionsLanguageServer()


@server.feature(lsp.INITIALIZE)
def initialize(params: lsp.InitializeParams) -> lsp.InitializeResult:
    """Handle initialize request."""
    logger.info("Initializing Agent Actions LSP...")

    # Find project root from workspace folders
    if params.workspace_folders:
        for folder in params.workspace_folders:
            folder_path = uri_to_path(folder.uri)
            root = find_project_root(folder_path)
            if root:
                server.project_root = root
                server.index = build_index(root)
                logger.info(f"Indexed project at {root}")
                break

    return lsp.InitializeResult(
        capabilities=lsp.ServerCapabilities(
            text_document_sync=lsp.TextDocumentSyncOptions(
                open_close=True,
                change=lsp.TextDocumentSyncKind.Incremental,
                save=lsp.SaveOptions(include_text=True),
            ),
            definition_provider=True,
            hover_provider=True,
            completion_provider=lsp.CompletionOptions(
                trigger_characters=["$", ":", ".", "-"],
                resolve_provider=False,
            ),
            signature_help_provider=lsp.SignatureHelpOptions(
                trigger_characters=[":"],
            ),
            document_symbol_provider=True,
            document_highlight_provider=True,
            code_lens_provider=lsp.CodeLensOptions(resolve_provider=False),
            semantic_tokens_provider=lsp.SemanticTokensOptions(
                legend=_semantic_tokens_legend(),
                full=True,
                range=False,
            ),
        ),
        server_info=lsp.ServerInfo(
            name="agent-actions-lsp",
            version="0.1.0",
        ),
    )


@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
def goto_definition(params: lsp.DefinitionParams) -> Optional[lsp.Location]:
    """Handle go to definition request."""
    if not server.index:
        return None

    # Get document content
    doc = server.workspace.get_text_document(params.text_document.uri)
    if not doc:
        return None

    # Get reference at cursor position
    reference = get_reference_at_position(
        content=doc.source,
        line=params.position.line,
        character=params.position.character,
    )

    if not reference:
        return None

    # Resolve the reference
    current_file = uri_to_path(params.text_document.uri)
    location = resolve_reference(reference, server.index, current_file)

    if not location:
        return None

    return lsp.Location(
        uri=location.file_path.as_uri(),
        range=lsp.Range(
            start=lsp.Position(line=location.line, character=location.column),
            end=lsp.Position(
                line=location.end_line or location.line,
                character=location.end_column or location.column + 10,
            ),
        ),
    )


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
def hover(params: lsp.HoverParams) -> Optional[lsp.Hover]:
    """Handle hover request."""
    if not server.index:
        return None

    doc = server.workspace.get_text_document(params.text_document.uri)
    if not doc:
        return None

    reference = get_reference_at_position(
        content=doc.source,
        line=params.position.line,
        character=params.position.character,
    )

    if not reference:
        return None

    # Build hover content based on reference type
    content = _build_hover_content(reference, server.index)
    if not content:
        return None

    return lsp.Hover(
        contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=content,
        )
    )


def _build_hover_content(reference, index: ProjectIndex) -> Optional[str]:
    """Build markdown hover content for a reference."""
    if reference.type == ReferenceType.PROMPT:
        prompt = index.get_prompt(reference.value)
        if prompt:
            return f"**Prompt**: `{prompt.full_name}`\n\n```\n{prompt.content_preview}\n```"

    elif reference.type == ReferenceType.TOOL:
        tool = index.get_tool(reference.value)
        if tool:
            content = f"**Tool**: `{tool.name}`\n\n```python\n{tool.signature}\n```"
            if tool.docstring:
                content += f"\n\n{tool.docstring}"
            return content

    elif reference.type == ReferenceType.SCHEMA:
        schema = index.get_schema_definition(reference.value)
        if schema:
            fields_preview = ""
            if schema.fields:
                field_lines = "\n".join(f"- `{field}`" for field in schema.fields[:8])
                fields_preview = f"\n\n**Fields**\n{field_lines}"
            return f"**Schema**: `{reference.value}`\n\nFile: `{schema.location.file_path}`{fields_preview}"

    elif reference.type == ReferenceType.ACTION:
        location = index.get_action(reference.value)
        if location:
            return f"**Action**: `{reference.value}`\n\nDefined at line {location.line + 1}"

    return None


@server.feature(lsp.TEXT_DOCUMENT_COMPLETION)
def completions(params: lsp.CompletionParams) -> lsp.CompletionList:
    """Handle completion request."""
    if not server.index:
        return lsp.CompletionList(is_incomplete=False, items=[])

    doc = server.workspace.get_text_document(params.text_document.uri)
    if not doc:
        return lsp.CompletionList(is_incomplete=False, items=[])

    # Get the current line
    lines = doc.source.split("\n")
    if params.position.line >= len(lines):
        return lsp.CompletionList(is_incomplete=False, items=[])

    line = lines[params.position.line]
    line_before_cursor = line[: params.position.character]

    items = []

    # Prompt completions (after $)
    if "$" in line_before_cursor and "prompt" in line.lower():
        for name, prompt in server.index.prompts.items():
            items.append(
                lsp.CompletionItem(
                    label=name,
                    kind=lsp.CompletionItemKind.Reference,
                    detail="Prompt",
                    documentation=prompt.content_preview[:100] if prompt.content_preview else None,
                )
            )

    # Tool completions (after impl:)
    elif "impl:" in line_before_cursor:
        for name, tool in server.index.tools.items():
            items.append(
                lsp.CompletionItem(
                    label=name,
                    kind=lsp.CompletionItemKind.Function,
                    detail="UDF Tool",
                    documentation=tool.docstring[:100] if tool.docstring else None,
                )
            )

    # Schema completions (after schema:)
    elif "schema:" in line_before_cursor:
        for name in server.index.schemas:
            items.append(
                lsp.CompletionItem(
                    label=name,
                    kind=lsp.CompletionItemKind.File,
                    detail="Schema",
                )
            )

    # Action completions (in dependencies)
    elif is_in_dependencies_context(lines, params.position.line):
        for name in server.index.actions:
            items.append(
                lsp.CompletionItem(
                    label=name,
                    kind=lsp.CompletionItemKind.Module,
                    detail="Action",
                )
            )

    # Context scope completions
    elif _is_in_context_scope_block(lines, params.position.line):
        current_file = uri_to_path(params.text_document.uri)
        items.extend(_build_context_scope_completions(current_file))

    # Guard/reprompt completions
    elif "condition:" in line_before_cursor or "validation:" in line_before_cursor:
        current_file = uri_to_path(params.text_document.uri)
        items.extend(_build_guard_completions(current_file))

    # Versions block completions
    elif _is_in_versions_block(lines, params.position.line):
        for key in ("param", "range", "mode", "source", "pattern"):
            items.append(
                lsp.CompletionItem(
                    label=key,
                    kind=lsp.CompletionItemKind.Property,
                    detail="Versions key",
                )
            )

    return lsp.CompletionList(is_incomplete=False, items=items)


@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbols(params: lsp.DocumentSymbolParams) -> list[lsp.DocumentSymbol]:
    """Handle document symbols request (outline view)."""
    if not server.index:
        return []

    doc = server.workspace.get_text_document(params.text_document.uri)
    if not doc:
        return []

    file_path = uri_to_path(params.text_document.uri)
    symbols = []

    # Handle YAML workflow files - show actions
    if file_path in server.index.file_actions:
        for name, action_meta in server.index.file_actions[file_path].items():
            location = action_meta.location
            symbols.append(
                lsp.DocumentSymbol(
                    name=name,
                    kind=lsp.SymbolKind.Function,
                    range=lsp.Range(
                        start=lsp.Position(line=location.line, character=0),
                        end=lsp.Position(line=location.line + 1, character=0),
                    ),
                    selection_range=lsp.Range(
                        start=lsp.Position(line=location.line, character=location.column),
                        end=lsp.Position(line=location.line, character=location.column + len(name)),
                    ),
                )
            )

    # Handle Markdown prompt files - show {prompt} blocks
    if file_path.suffix == ".md":
        symbols.extend(_get_prompt_symbols(doc.source, file_path))

    return symbols


def _get_prompt_symbols(content: str, file_path: Path) -> list[lsp.DocumentSymbol]:
    """Extract prompt block symbols from markdown content."""
    import re

    symbols = []
    lines = content.split("\n")

    prompt_start = re.compile(r"\{prompt\s+(\w+)\}")
    prompt_end = re.compile(r"\{end_prompt\}")

    current_prompt = None
    current_start_line = 0

    for i, line in enumerate(lines):
        # Check for prompt start
        start_match = prompt_start.search(line)
        if start_match:
            current_prompt = start_match.group(1)
            current_start_line = i
            continue

        # Check for prompt end
        if current_prompt and prompt_end.search(line):
            symbols.append(
                lsp.DocumentSymbol(
                    name=current_prompt,
                    kind=lsp.SymbolKind.String,
                    range=lsp.Range(
                        start=lsp.Position(line=current_start_line, character=0),
                        end=lsp.Position(line=i + 1, character=0),
                    ),
                    selection_range=lsp.Range(
                        start=lsp.Position(line=current_start_line, character=0),
                        end=lsp.Position(
                            line=current_start_line, character=len(lines[current_start_line])
                        ),
                    ),
                )
            )
            current_prompt = None

    return symbols


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(params: lsp.DidSaveTextDocumentParams):
    """Handle file save - reindex the file."""
    if not server.project_root:
        return

    # Rebuild full index for now (can optimize later)
    server.index = build_index(server.project_root)
    logger.info("Reindexed project after save")
    _publish_diagnostics(params.text_document.uri)


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(params: lsp.DidOpenTextDocumentParams):
    """Handle file open - publish diagnostics."""
    _publish_diagnostics(params.text_document.uri)


@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
def document_highlight(params: lsp.DocumentHighlightParams) -> list[lsp.DocumentHighlight]:
    """Highlight references under cursor."""
    if not server.index:
        return []

    file_path = uri_to_path(params.text_document.uri)
    references = server.index.references_by_file.get(file_path, [])
    target = _find_reference_at_position(
        references, params.position.line, params.position.character
    )
    if not target:
        return []

    highlights = []
    for reference in references:
        if reference.type == target.type and reference.value == target.value:
            highlights.append(
                lsp.DocumentHighlight(
                    range=lsp.Range(
                        start=lsp.Position(
                            line=reference.location.line, character=reference.location.column
                        ),
                        end=lsp.Position(
                            line=reference.location.end_line or reference.location.line,
                            character=reference.location.end_column or reference.location.column,
                        ),
                    )
                )
            )
    return highlights


@server.feature(lsp.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL)
def semantic_tokens(params: lsp.SemanticTokensParams) -> lsp.SemanticTokens:
    """Provide semantic tokens for references in workflow files."""
    if not server.index:
        return lsp.SemanticTokens(data=[])

    file_path = uri_to_path(params.text_document.uri)
    references = server.index.references_by_file.get(file_path, [])
    tokens = _build_semantic_tokens(references)
    return lsp.SemanticTokens(data=tokens)


@server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)
def code_lens(params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
    """Provide code lenses for guard and versions blocks."""
    if not server.index:
        return []

    file_path = uri_to_path(params.text_document.uri)
    actions = server.index.file_actions.get(file_path, {})
    lenses: list[lsp.CodeLens] = []

    for action in actions.values():
        if action.versions_line is not None and action.versions_summary:
            lenses.append(
                lsp.CodeLens(
                    range=lsp.Range(
                        start=lsp.Position(line=action.versions_line, character=0),
                        end=lsp.Position(line=action.versions_line, character=0),
                    ),
                    command=lsp.Command(
                        title=f"Versions: {action.versions_summary}",
                        command="agent-actions.showVersionsSummary",
                        arguments=[action.name],
                    ),
                )
            )
        if action.guard_line is not None and action.guard_condition:
            lenses.append(
                lsp.CodeLens(
                    range=lsp.Range(
                        start=lsp.Position(line=action.guard_line, character=0),
                        end=lsp.Position(line=action.guard_line, character=0),
                    ),
                    command=lsp.Command(
                        title=f"Guard: {action.guard_condition}",
                        command="agent-actions.showGuardSummary",
                        arguments=[action.name],
                    ),
                )
            )

    return lenses


@server.feature(lsp.TEXT_DOCUMENT_SIGNATURE_HELP)
def signature_help(params: lsp.SignatureHelpParams) -> Optional[lsp.SignatureHelp]:
    """Provide signature help for guard/reprompt conditions."""
    if not server.index:
        return None

    doc = server.workspace.get_text_document(params.text_document.uri)
    if not doc:
        return None

    lines = doc.source.split("\n")
    if params.position.line >= len(lines):
        return None

    line = lines[params.position.line]
    if "condition:" not in line and "validation:" not in line:
        return None

    current_file = uri_to_path(params.text_document.uri)
    variables = _collect_available_guard_variables(current_file)
    if not variables:
        return None

    signature = lsp.SignatureInformation(
        label="Available variables: " + ", ".join(sorted(variables)),
        documentation="Variables derived from context_scope.observe and action schemas.",
    )
    return lsp.SignatureHelp(signatures=[signature], active_signature=0, active_parameter=0)


def _semantic_tokens_legend() -> lsp.SemanticTokensLegend:
    """Define semantic tokens legend."""
    return lsp.SemanticTokensLegend(
        token_types=SEMANTIC_TOKEN_TYPES,
        token_modifiers=[],
    )


def _build_semantic_tokens(references) -> list[int]:
    """Build semantic tokens for references."""
    legend = _semantic_tokens_legend().token_types
    sorted_refs = sorted(references, key=lambda ref: (ref.location.line, ref.location.column))
    data = []
    last_line = 0
    last_char = 0

    for reference in sorted_refs:
        token_type_name = SEMANTIC_TOKEN_TYPE_MAP.get(reference.type)
        if not token_type_name:
            continue
        token_type_index = legend.index(token_type_name)
        line = reference.location.line
        start_char = reference.location.column
        length = (reference.location.end_column or start_char) - start_char
        delta_line = line - last_line
        delta_start = start_char - last_char if delta_line == 0 else start_char
        data.extend([delta_line, delta_start, max(length, 1), token_type_index, 0])
        last_line = line
        last_char = start_char

    return data


def _find_reference_at_position(references, line: int, character: int):
    """Find the reference that contains the given position."""
    for reference in references:
        loc = reference.location
        end_col = loc.end_column or loc.column
        if loc.line == line and loc.column <= character <= end_col:
            return reference
    return None


def _publish_diagnostics(uri: str) -> None:
    """Publish diagnostics for a file."""
    if not server.index:
        return

    doc = server.workspace.get_text_document(uri)
    if not doc:
        return

    file_path = uri_to_path(uri)
    diagnostics = _collect_diagnostics(file_path, server.index)
    server.text_document_publish_diagnostics(
        lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
    )


def _collect_diagnostics(file_path: Path, index: ProjectIndex) -> list[lsp.Diagnostic]:
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
                            lsp.DiagnosticSeverity.Warning,
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
            available = _collect_available_guard_variables(file_path)
            for variable in action.guard_variables:
                if variable not in available:
                    diagnostics.append(
                        _build_diagnostic(
                            Location(
                                file_path=file_path,
                                line=action.guard_line or action.location.line,
                                column=0,
                            ),
                            f"Guard condition references `{variable}` which is not observed "
                            "in context_scope.",
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


def _split_context_reference(value: str) -> tuple[str, Optional[str]]:
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


def _is_in_context_scope_block(lines: list[str], line_number: int) -> bool:
    """Check if a line is inside a context_scope block."""
    current_indent = len(lines[line_number]) - len(lines[line_number].lstrip())
    for i in range(line_number, -1, -1):
        line = lines[i]
        if not line.strip():
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent < current_indent and line.strip().startswith("context_scope:"):
            return True
        if line_indent < current_indent and line.strip().startswith("-"):
            continue
        if line_indent <= current_indent and line.strip().startswith("context_scope:"):
            return True
    return False


def _is_in_versions_block(lines: list[str], line_number: int) -> bool:
    """Check if a line is inside a versions block."""
    current_indent = len(lines[line_number]) - len(lines[line_number].lstrip())
    for i in range(line_number, -1, -1):
        line = lines[i]
        if not line.strip():
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent < current_indent and line.strip().startswith("versions:"):
            return True
        if line_indent <= current_indent and line.strip().startswith("versions:"):
            return True
    return False


def _build_context_scope_completions(file_path: Path) -> list[lsp.CompletionItem]:
    """Build completions for context_scope observe/drop blocks."""
    if not server.index:
        return []
    items = []
    actions = server.index.file_actions.get(file_path, {})
    for action in actions.values():
        if action.schema_ref:
            schema = server.index.get_schema_definition(action.schema_ref)
            if schema and schema.fields:
                for field in schema.fields:
                    items.append(
                        lsp.CompletionItem(
                            label=f"{action.name}.{field}",
                            kind=lsp.CompletionItemKind.Field,
                            detail=f"Output field from {action.name}",
                        )
                    )
        items.append(
            lsp.CompletionItem(
                label=action.name,
                kind=lsp.CompletionItemKind.Module,
                detail="Action output",
            )
        )
    return items


def _build_guard_completions(file_path: Path) -> list[lsp.CompletionItem]:
    """Build completions for guard/reprompt conditions."""
    variables = _collect_available_guard_variables(file_path)
    return [
        lsp.CompletionItem(
            label=variable,
            kind=lsp.CompletionItemKind.Variable,
            detail="Context variable",
        )
        for variable in sorted(variables)
    ]


def _collect_available_guard_variables(file_path: Path) -> set[str]:
    """Collect variables available for guard/reprompt conditions."""
    if not server.index:
        return set()

    actions = server.index.file_actions.get(file_path, {})
    variables: set[str] = set()
    for action in actions.values():
        for observed in action.context_observe:
            variables.add(observed)
            if "." in observed:
                _, field = observed.split(".", 1)
                variables.add(field)
        for passthrough in action.context_passthrough:
            variables.add(passthrough)
            if "." in passthrough:
                _, field = passthrough.split(".", 1)
                variables.add(field)
        if action.schema_ref:
            schema = server.index.get_schema_definition(action.schema_ref)
            if schema:
                for field in schema.fields:
                    variables.add(f"{action.name}.{field}")
    return variables


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Agent Actions LSP Server")
    parser.add_argument("--stdio", action="store_true", help="Use stdio transport")
    parser.add_argument("--tcp", action="store_true", help="Use TCP transport")
    parser.add_argument("--port", type=int, default=2087, help="TCP port (default: 2087)")

    args = parser.parse_args()

    if args.tcp:
        server.start_tcp("127.0.0.1", args.port)
    else:
        server.start_io()


if __name__ == "__main__":
    main()
