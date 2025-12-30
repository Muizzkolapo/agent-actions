"""User-facing error data structure."""

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class UserError:
    """Structured representation of a user-facing error."""

    category: str  # Configuration, Model, Provider, File, Network, Authentication
    title: str  # Brief description
    details: Optional[str] = None  # What went wrong
    fix: Optional[str] = None  # How to fix it
    context: Optional[Dict[str, Any]] = None  # agent, file, field, etc.
    docs_url: Optional[str] = None

    def format_for_cli(self) -> str:
        """Format error for CLI display."""
        lines = [f"{self.category}: {self.title}"]

        if self.details:
            lines.extend(["", f"  Problem: {self.details}"])

        # Add context information
        # Display specific important fields first
        if self.context:
            if "agent" in self.context:
                lines.append(f"  Agent: {self.context['agent']}")
            if "file_path" in self.context:
                lines.append(f"  File: {self.context['file_path']}")
            if "field" in self.context:
                lines.append(f"  Field: {self.context['field']}")
            if "model" in self.context:
                lines.append(f"  Model: {self.context['model']}")
            if "provider" in self.context:
                lines.append(f"  Provider: {self.context['provider']}")

            # Display other context fields (for debugging and completeness)
            # Skip internal/technical fields and already-displayed fields
            displayed_fields = {"agent", "file_path", "field", "model", "provider"}
            skip_fields = {"function", "module", "resource_type"}  # Internal technical fields

            other_context = {
                k: v
                for k, v in self.context.items()
                if k not in displayed_fields and k not in skip_fields
            }

            if other_context:
                lines.append("")
                lines.append("  Context:")
                for key, value in sorted(other_context.items()):
                    lines.append(f"    {key}: {value}")

        if self.fix:
            lines.extend(["", f"  Fix: {self.fix}"])

        if self.docs_url:
            lines.extend(["", f"  Learn more: {self.docs_url}"])

        return "\n".join(lines)
