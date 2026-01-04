"""Agent Actions LSP Server - Main entry point."""

import logging
from pathlib import Path
from typing import Optional

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from .indexer import build_index, find_project_root
from .models import ProjectIndex, ReferenceType
from .resolver import get_reference_at_position, resolve_reference

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
            folder_path = Path(folder.uri.replace("file://", ""))
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
            document_symbol_provider=True,
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
    current_file = Path(params.text_document.uri.replace("file://", ""))
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
        schema_path = index.get_schema(reference.value)
        if schema_path:
            return f"**Schema**: `{reference.value}`\n\nFile: `{schema_path}`"

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
    elif "dependencies:" in line or line_before_cursor.strip().startswith("-"):
        for name in server.index.actions:
            items.append(
                lsp.CompletionItem(
                    label=name,
                    kind=lsp.CompletionItemKind.Module,
                    detail="Action",
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

    file_path = Path(params.text_document.uri.replace("file://", ""))
    symbols = []

    # Handle YAML workflow files - show actions
    if file_path in server.index.file_actions:
        for name, location in server.index.file_actions[file_path].items():
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
