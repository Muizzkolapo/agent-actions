"""User-facing error data structure."""

from dataclasses import dataclass
from typing import Any

# Fields to display prominently with their labels
_PRIORITY_FIELDS = [
    ("agent", "Agent"),
    ("file_path", "File"),
    ("field", "Field"),
    ("model", "Model"),
    ("provider", "Provider"),
    ("mode", "Mode"),
]

# Internal technical fields and CLI flags to never show
_SKIP_FIELDS = {
    "function",
    "module",
    "resource_type",  # Internal technical
    "command",
    "concurrency_limit",
    "downstream",
    "execution_mode",  # CLI flags
    "force",
    "static_typing",
    "upstream",
    "use_tools",
    "user_code",  # CLI flags
    "all_issues",
    "total_errors",
    "total_warnings",  # Validation internals
    "hint",  # Shown separately in fix section
}

# Fields useful for debugging context
_USEFUL_DEBUG_FIELDS = {
    "agent_name",
    "workflow",
    "batch_name",
    "template_line",
    "staged_fields",
    "validation_phase",  # Staging validation context
}


def _truncate_list(items: list[Any], max_items: int = 10) -> list[Any]:
    """Truncate a list and add a count of remaining items."""
    if len(items) <= max_items:
        return items
    return items[:max_items] + [f"(+{len(items) - max_items} more)"]


@dataclass
class UserError:
    """Structured representation of a user-facing error."""

    category: str  # Configuration, Model, Provider, File, Network, Authentication
    title: str  # Brief description
    details: str | None = None  # What went wrong
    fix: str | None = None  # How to fix it
    context: dict[str, Any] | None = None  # agent, file, field, etc.
    docs_url: str | None = None

    def _format_context(self, lines: list[str]) -> None:
        """Format context fields into output lines."""
        if not self.context:
            return

        # Display priority fields first
        for key, label in _PRIORITY_FIELDS:
            if key in self.context:
                lines.append(f"  {label}: {self.context[key]}")

        # Display missing/available references prominently
        missing = self.context.get("missing_references")
        if missing:
            lines.append(f"  Missing: {', '.join(str(r) for r in missing)}")

        refs = self.context.get("available_references")
        if refs:
            display_refs = _truncate_list(refs) if isinstance(refs, list) else refs
            lines.append(f"  Available: {', '.join(str(r) for r in display_refs)}")

        # Filter to useful debug fields only
        displayed = {k for k, _ in _PRIORITY_FIELDS} | {
            "missing_references",
            "available_references",
        }
        debug_context = {
            k: v
            for k, v in self.context.items()
            if k in _USEFUL_DEBUG_FIELDS and k not in displayed and k not in _SKIP_FIELDS
        }

        if debug_context:
            lines.extend(["", "  Context:"])
            for key, value in sorted(debug_context.items()):
                lines.append(f"    {key}: {value}")

    def format_for_cli(self) -> str:
        """Format error for CLI display."""
        lines = [f"{self.category}: {self.title}"]

        if self.details:
            lines.extend(["", f"  Problem: {self.details}"])

        self._format_context(lines)

        if self.fix:
            lines.extend(["", f"  Fix: {self.fix}"])

        if self.docs_url:
            lines.extend(["", f"  Learn more: {self.docs_url}"])

        return "\n".join(lines)
