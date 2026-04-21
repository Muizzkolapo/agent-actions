"""Agent Actions LSP Server - Main entry point."""

import logging
from pathlib import Path

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from agent_actions.config.path_config import get_schema_path, get_tool_dirs
from agent_actions.errors import ConfigValidationError

from .completions import (
    build_context_scope_completions,
    build_guard_completions,
    is_in_context_scope_block,
    is_in_versions_block,
)
from .diagnostics import (
    collect_available_guard_variables,
    collect_diagnostics,
    publish_diagnostics,
)
from .handlers import (
    build_hover_content,
    build_semantic_tokens,
    find_reference_at_position,
    get_prompt_symbols,
    semantic_tokens_legend,
)
from .indexer import build_index, find_all_project_roots, find_project_root
from .models import ProjectIndex
from .resolver import get_reference_at_position, resolve_reference
from .utils import is_in_dependencies_context, uri_to_path

logger = logging.getLogger(__name__)


class AgentActionsLanguageServer(LanguageServer):
    """Language Server for agent-actions workflows."""

    def __init__(self):
        super().__init__("agent-actions-lsp", "v0.1.0")
        self.project_indexes: dict[Path, ProjectIndex] = {}
        self.index: ProjectIndex | None = None  # convenience alias for the primary project
        self.project_root: Path | None = None  # convenience alias for the primary project root


# Create server instance
server = AgentActionsLanguageServer()


def _index_for_file(file_path: Path) -> ProjectIndex | None:
    """Route a file to its correct project index (deepest matching root wins).

    Returns None when the file does not belong to any indexed project,
    preventing silent cross-project leakage.
    """
    best_root = None
    best_depth = -1
    resolved = file_path.resolve()
    for root in server.project_indexes:
        try:
            resolved.relative_to(root)
            if len(root.parts) > best_depth:
                best_root = root
                best_depth = len(root.parts)
        except ValueError:
            continue
    return server.project_indexes[best_root] if best_root else None


def _reindex_project(root: Path) -> None:
    """Rebuild a project's index and sync the backward-compat alias."""
    server.project_indexes[root] = build_index(root)
    if server.project_root == root:
        server.index = server.project_indexes[root]


# ---------------------------------------------------------------------------
# Request handlers
# ---------------------------------------------------------------------------


@server.feature(lsp.INITIALIZE)
def initialize(params: lsp.InitializeParams) -> lsp.InitializeResult:
    """Handle initialize request."""
    logger.info("Initializing Agent Actions LSP...")

    if params.workspace_folders:
        folder_paths = [uri_to_path(f.uri) for f in params.workspace_folders]
        roots = find_all_project_roots(folder_paths)

        for root in roots:
            idx = build_index(root)
            server.project_indexes[root] = idx
            logger.info("Indexed project at %s", root)

        # Backward-compat: first project or single-folder fallback
        if server.project_indexes:
            first_root = next(iter(server.project_indexes))
            server.project_root = first_root
            server.index = server.project_indexes[first_root]
        elif folder_paths:
            fallback_root = find_project_root(folder_paths[0])
            if fallback_root:
                server.project_root = fallback_root
                server.index = build_index(fallback_root)
                server.project_indexes[fallback_root] = server.index
                logger.info("Indexed project at %s", fallback_root)

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
                legend=semantic_tokens_legend(),
                full=True,
                range=False,
            ),
        ),
        server_info=lsp.ServerInfo(
            name="agent-actions-lsp",
            version="0.1.0",
        ),
    )


@server.feature(lsp.INITIALIZED)
def initialized(params: lsp.InitializedParams):
    """Register file watchers after client initialization."""
    _register_file_watchers()


@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
def goto_definition(params: lsp.DefinitionParams) -> lsp.Location | None:
    """Handle go to definition request."""
    current_file = uri_to_path(params.text_document.uri)
    index = _index_for_file(current_file)
    if not index:
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

    location = resolve_reference(reference, index, current_file)

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
def hover(params: lsp.HoverParams) -> lsp.Hover | None:
    """Handle hover request."""
    current_file = uri_to_path(params.text_document.uri)
    index = _index_for_file(current_file)
    if not index:
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

    content = build_hover_content(reference, index, current_file=current_file)
    if not content:
        return None

    return lsp.Hover(
        contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=content,
        )
    )


@server.feature(lsp.TEXT_DOCUMENT_COMPLETION)
def completions(params: lsp.CompletionParams) -> lsp.CompletionList:
    """Handle completion request."""
    current_file = uri_to_path(params.text_document.uri)
    index = _index_for_file(current_file)
    if not index:
        return lsp.CompletionList(is_incomplete=False, items=[])

    doc = server.workspace.get_text_document(params.text_document.uri)
    if not doc:
        return lsp.CompletionList(is_incomplete=False, items=[])

    lines = doc.source.split("\n")
    if params.position.line >= len(lines):
        return lsp.CompletionList(is_incomplete=False, items=[])

    line = lines[params.position.line]
    line_before_cursor = line[: params.position.character]

    items = []

    # Prompt completions (after $)
    if "$" in line_before_cursor and "prompt" in line.lower():
        for name, prompt in index.prompts.items():
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
        for name, tool in index.tools.items():
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
        for name in index.schemas:
            items.append(
                lsp.CompletionItem(
                    label=name,
                    kind=lsp.CompletionItemKind.File,
                    detail="Schema",
                )
            )

    # Action completions (in dependencies) — prefer workflow-scoped actions
    elif is_in_dependencies_context(lines, params.position.line):
        workflow = index.workflow_for_file(current_file)
        action_names = (
            index.workflow_actions.get(workflow, index.actions) if workflow else index.actions
        )
        for name in action_names:
            items.append(
                lsp.CompletionItem(
                    label=name,
                    kind=lsp.CompletionItemKind.Module,
                    detail="Action",
                )
            )

    # Context scope completions
    elif is_in_context_scope_block(lines, params.position.line):
        items.extend(build_context_scope_completions(current_file, index))

    # Guard/reprompt completions
    elif "condition:" in line_before_cursor or "validation:" in line_before_cursor:
        items.extend(build_guard_completions(current_file, index))

    # Versions block completions
    elif is_in_versions_block(lines, params.position.line):
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
    file_path = uri_to_path(params.text_document.uri)
    index = _index_for_file(file_path)
    if not index:
        return []

    doc = server.workspace.get_text_document(params.text_document.uri)
    if not doc:
        return []

    symbols = []

    if file_path in index.file_actions:
        for name, action_meta in index.file_actions[file_path].items():
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

    if file_path.suffix == ".md":
        symbols.extend(get_prompt_symbols(doc.source, file_path))

    return symbols


# ---------------------------------------------------------------------------
# Notification handlers
# ---------------------------------------------------------------------------


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(params: lsp.DidSaveTextDocumentParams):
    """Handle file save - reindex affected project(s)."""
    file_path = uri_to_path(params.text_document.uri)

    # New agent_actions.yml -> register as new project if not tracked
    if file_path.name == "agent_actions.yml":
        new_root = file_path.parent.resolve()
        if new_root not in server.project_indexes:
            idx = build_index(new_root)
            server.project_indexes[new_root] = idx
            if not server.project_root:
                server.project_root = new_root
                server.index = idx
            logger.info("Registered new project at %s", new_root)
        else:
            _reindex_project(new_root)
            logger.info("Reindexed project at %s", new_root)
    else:
        file_idx = _index_for_file(file_path)
        if file_idx:
            _reindex_project(file_idx.root)
            logger.info("Reindexed project at %s after save", file_idx.root)

    _publish_diagnostics(params.text_document.uri)


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(params: lsp.DidOpenTextDocumentParams):
    """Handle file open - publish diagnostics."""
    _publish_diagnostics(params.text_document.uri)


@server.feature(lsp.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def did_change_watched_files(params: lsp.DidChangeWatchedFilesParams):
    """Handle external file changes — reindex affected projects."""
    affected_roots: set[Path] = set()

    for event in params.changes:
        file_path = uri_to_path(event.uri)

        if file_path.name == "agent_actions.yml":
            root = file_path.parent.resolve()
            if event.type == lsp.FileChangeType.Deleted:
                if root in server.project_indexes:
                    del server.project_indexes[root]
                    _clear_diagnostics_for_root(root)
                    if server.project_root == root:
                        if server.project_indexes:
                            first = next(iter(server.project_indexes))
                            server.project_root = first
                            server.index = server.project_indexes[first]
                        else:
                            server.project_root = None
                            server.index = None
                    logger.info("Removed project at %s", root)
                continue
            # Created or Changed
            if root not in server.project_indexes:
                idx = build_index(root)
                server.project_indexes[root] = idx
                if not server.project_root:
                    server.project_root = root
                    server.index = idx
                logger.info("Registered new project at %s via watcher", root)
                _register_file_watchers()
            else:
                affected_roots.add(root)
            continue

        file_idx = _index_for_file(file_path)
        if file_idx:
            affected_roots.add(file_idx.root)

    for root in affected_roots:
        _reindex_project(root)
        logger.info("Reindexed project at %s after watched file change", root)

    _republish_diagnostics_for_projects(affected_roots)


@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
def document_highlight(params: lsp.DocumentHighlightParams) -> list[lsp.DocumentHighlight]:
    """Highlight references under cursor."""
    file_path = uri_to_path(params.text_document.uri)
    index = _index_for_file(file_path)
    if not index:
        return []

    references = index.references_by_file.get(file_path, [])
    target = find_reference_at_position(references, params.position.line, params.position.character)
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
    file_path = uri_to_path(params.text_document.uri)
    index = _index_for_file(file_path)
    if not index:
        return lsp.SemanticTokens(data=[])

    references = index.references_by_file.get(file_path, [])
    tokens = build_semantic_tokens(references)
    return lsp.SemanticTokens(data=tokens)


@server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)
def code_lens(params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
    """Provide code lenses for guard and versions blocks."""
    file_path = uri_to_path(params.text_document.uri)
    index = _index_for_file(file_path)
    if not index:
        return []

    actions = index.file_actions.get(file_path, {})
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
def signature_help(params: lsp.SignatureHelpParams) -> lsp.SignatureHelp | None:
    """Provide signature help for guard/reprompt conditions."""
    current_file = uri_to_path(params.text_document.uri)
    index = _index_for_file(current_file)
    if not index:
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

    variables = collect_available_guard_variables(current_file, index)
    if not variables:
        return None

    signature = lsp.SignatureInformation(
        label="Available variables: " + ", ".join(sorted(variables)),
        documentation="Variables derived from context_scope.observe and action schemas.",
    )
    return lsp.SignatureHelp(signatures=[signature], active_signature=0, active_parameter=0)


# ---------------------------------------------------------------------------
# Internal helpers (thin wrappers around extracted modules)
# ---------------------------------------------------------------------------


def _publish_diagnostics(uri: str) -> None:
    """Publish diagnostics for a file."""
    publish_diagnostics(
        uri,
        get_index_for_file=_index_for_file,
        get_text_document=server.workspace.get_text_document,
        publish_fn=server.text_document_publish_diagnostics,
    )


def _republish_diagnostics_for_projects(roots: set[Path]) -> None:
    """Republish diagnostics for all open documents in the given projects."""
    if not roots:
        return
    for uri in list(server.workspace.text_documents):
        file_path = uri_to_path(uri)
        idx = _index_for_file(file_path)
        if idx and idx.root in roots:
            _publish_diagnostics(uri)


def _clear_diagnostics_for_root(root: Path) -> None:
    """Clear diagnostics for all open documents that belonged to a removed project."""
    for uri in list(server.workspace.text_documents):
        file_path = uri_to_path(uri)
        try:
            file_path.resolve().relative_to(root)
        except ValueError:
            continue
        server.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=[])
        )


def _register_file_watchers() -> None:
    """Dynamically register file system watchers for all indexed projects."""
    watchers: list[lsp.FileSystemWatcher] = []
    for root in server.project_indexes:
        watchers.extend(_build_watchers_for_project(root))
    if not watchers:
        return

    registration = lsp.Registration(
        id="agent-actions-file-watchers",
        method=lsp.WORKSPACE_DID_CHANGE_WATCHED_FILES,
        register_options=lsp.DidChangeWatchedFilesRegistrationOptions(
            watchers=watchers,
        ),
    )
    try:
        server.client_register_capability(
            lsp.RegistrationParams(registrations=[registration]),
        )
        logger.info("Registered %d file watchers", len(watchers))
    except Exception:  # Protocol boundary — client may not support dynamic registration
        logger.debug("Dynamic file watcher registration not available", exc_info=True)


def _build_watchers_for_project(root: Path) -> list[lsp.FileSystemWatcher]:
    """Build file system watchers for a single project."""
    kind = lsp.WatchKind.Create | lsp.WatchKind.Change | lsp.WatchKind.Delete
    watchers: list[lsp.FileSystemWatcher] = []
    root_uri = root.as_uri()

    # Core patterns (always watched)
    for pattern in (
        "agent_actions.yml",
        "agent_workflow/*/agent_config/*.yml",
        "prompt_store/*.md",
    ):
        watchers.append(
            lsp.FileSystemWatcher(
                glob_pattern=lsp.RelativePattern(base_uri=root_uri, pattern=pattern),
                kind=kind,
            )
        )

    # Tool directories (from config, default: ["tools"])
    try:
        tool_dirs = get_tool_dirs(root)
    except (ConfigValidationError, OSError):
        tool_dirs = ["tools"]
    for td in tool_dirs:
        watchers.append(
            lsp.FileSystemWatcher(
                glob_pattern=lsp.RelativePattern(base_uri=root_uri, pattern=f"{td}/**/*.py"),
                kind=kind,
            )
        )

    # Schema directories (from config)
    try:
        schema_path = get_schema_path(root)
    except (ConfigValidationError, OSError):
        schema_path = None
    if schema_path:
        for ext in ("yml", "yaml", "json"):
            watchers.append(
                lsp.FileSystemWatcher(
                    glob_pattern=lsp.RelativePattern(
                        base_uri=root_uri, pattern=f"{schema_path}/**/*.{ext}"
                    ),
                    kind=kind,
                )
            )
            watchers.append(
                lsp.FileSystemWatcher(
                    glob_pattern=lsp.RelativePattern(
                        base_uri=root_uri,
                        pattern=f"agent_workflow/*/{schema_path}/**/*.{ext}",
                    ),
                    kind=kind,
                )
            )

    return watchers


# ---------------------------------------------------------------------------
# Backward-compatible private names kept for any external test imports
# ---------------------------------------------------------------------------

_build_hover_content = build_hover_content
_get_prompt_symbols = get_prompt_symbols
_find_reference_at_position = find_reference_at_position
_semantic_tokens_legend = semantic_tokens_legend
_build_semantic_tokens = build_semantic_tokens
_collect_diagnostics = collect_diagnostics
_collect_available_guard_variables = collect_available_guard_variables
_is_in_context_scope_block = is_in_context_scope_block
_is_in_versions_block = is_in_versions_block
_build_context_scope_completions = build_context_scope_completions
_build_guard_completions = build_guard_completions


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
