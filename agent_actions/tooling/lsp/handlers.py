"""LSP request/notification handler helpers — hover, semantic tokens, symbols."""

import json
import logging
import re

logger = logging.getLogger(__name__)

from lsprotocol import types as lsp

from ..rendering.data_card import render_card_markdown
from .models import ProjectIndex, ReferenceType

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


def build_hover_content(reference, index: ProjectIndex) -> str | None:
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

    elif reference.type == ReferenceType.SEED_FILE:
        return _build_seed_file_hover(reference, index)

    return None


def _build_seed_file_hover(reference, index: ProjectIndex) -> str | None:
    """Build a data-card style hover for a seed file reference.

    Attempts to read the first record from the referenced JSON file and
    render it as a card-formatted markdown preview.
    """
    file_path = reference.value
    # Resolve relative to project root
    if index.root:
        resolved = index.root / file_path
    else:
        return f"**Seed file**: `{file_path}`"

    if not resolved.is_file():
        return f"**Seed file**: `{file_path}`\n\n_File not found_"

    try:
        with open(resolved, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return f"**Seed file**: `{file_path}`\n\n_Could not read: {exc}_"

    # Extract first record for preview
    if isinstance(data, list) and len(data) > 0:
        record = data[0]
        total = len(data)
        header = f"**Seed file**: `{file_path}` ({total} records)\n\n"
    elif isinstance(data, dict):
        record = data
        header = f"**Seed file**: `{file_path}`\n\n"
    else:
        return f"**Seed file**: `{file_path}`\n\n_Empty or unsupported format_"

    if not isinstance(record, dict):
        return header + f"```json\n{json.dumps(record, indent=2)[:500]}\n```"

    return header + render_card_markdown(record)


def get_prompt_symbols(content: str, file_path) -> list[lsp.DocumentSymbol]:
    """Extract prompt block symbols from markdown content."""
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


def find_reference_at_position(references, line: int, character: int):
    """Find the reference that contains the given position."""
    for reference in references:
        loc = reference.location
        end_col = loc.end_column or loc.column
        if loc.line == line and loc.column <= character <= end_col:
            return reference
    return None


def semantic_tokens_legend() -> lsp.SemanticTokensLegend:
    """Define semantic tokens legend."""
    return lsp.SemanticTokensLegend(
        token_types=SEMANTIC_TOKEN_TYPES,
        token_modifiers=[],
    )


def build_semantic_tokens(references) -> list[int]:
    """Build semantic tokens for references."""
    legend = semantic_tokens_legend().token_types
    sorted_refs = sorted(references, key=lambda ref: (ref.location.line, ref.location.column))
    data = []
    last_line = 0
    last_char = 0

    for reference in sorted_refs:
        token_type_name = SEMANTIC_TOKEN_TYPE_MAP.get(reference.type)
        if not token_type_name:
            continue
        if token_type_name not in legend:
            logger.warning("Token type %r not in semantic tokens legend; skipping", token_type_name)
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
