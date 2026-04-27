"""Context scope -- reads from and filters the data bus for prompt rendering."""

from agent_actions.prompt.context.scope_application import (
    FRAMEWORK_NAMESPACES,
    apply_context_scope,
    apply_context_scope_for_records,
    format_llm_context,
)
from agent_actions.prompt.context.scope_builder import build_field_context_with_history

__all__ = [
    "FRAMEWORK_NAMESPACES",
    "apply_context_scope",
    "apply_context_scope_for_records",
    "build_field_context_with_history",
    "format_llm_context",
]
