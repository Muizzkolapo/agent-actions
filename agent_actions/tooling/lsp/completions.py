"""LSP completion provider logic."""

from pathlib import Path

from lsprotocol import types as lsp

from .models import ProjectIndex


def is_in_context_scope_block(lines: list[str], line_number: int) -> bool:
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


def is_in_versions_block(lines: list[str], line_number: int) -> bool:
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


def build_context_scope_completions(
    file_path: Path, index: ProjectIndex
) -> list[lsp.CompletionItem]:
    """Build completions for context_scope observe/drop blocks."""
    items = []
    actions = index.file_actions.get(file_path, {})
    for action in actions.values():
        if action.schema_ref:
            schema = index.get_schema_definition(action.schema_ref)
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


def build_guard_completions(file_path: Path, index: ProjectIndex) -> list[lsp.CompletionItem]:
    """Build completions for guard/reprompt conditions."""
    from .diagnostics import collect_available_guard_variables

    variables = collect_available_guard_variables(file_path, index)
    return [
        lsp.CompletionItem(
            label=variable,
            kind=lsp.CompletionItemKind.Variable,
            detail="Context variable",
        )
        for variable in sorted(variables)
    ]
