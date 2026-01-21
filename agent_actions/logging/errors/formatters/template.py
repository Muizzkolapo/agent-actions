"""Template rendering error formatter."""

from typing import Any, Dict, List

from .base import ErrorFormatter
from ..user_error import UserError


class TemplateErrorFormatter(ErrorFormatter):
    """Handles template rendering errors with missing variables."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        """Detect template variable errors."""
        exc_names = {type(exc).__name__, type(root).__name__}
        return "TemplateVariableError" in exc_names

    def format(
        self, exc: Exception, root: Exception, message: str, context: Dict[str, Any]
    ) -> UserError:
        """Format template variable errors with available context fields."""
        agent_name = context.get("agent") or context.get("agent_name") or "unknown"
        missing = context.get("missing_references", [])
        available = context.get("available_references", [])
        formatted_missing = ", ".join([f"'{field}'" for field in missing]) if missing else "unknown"

        details_lines: List[str] = [
            f"Template rendering failed for agent '{agent_name}'",
            "",
            f"  Missing field: {formatted_missing}",
        ]

        if available:
            available_display = ", ".join([str(field) for field in available])
            details_lines.append(f"  Available fields: [{available_display}]")

        hint = context.get("hint") or "Check that upstream agents produce the required fields."

        return UserError(
            category="Template Error",
            title="Template rendering failed",
            details="\n".join(details_lines),
            fix=hint,
            context={
                "agent": agent_name,
                "missing_references": missing,
                "available_references": available,
                "template_line": context.get("template_line"),
                "mode": context.get("mode"),
            },
            docs_url="https://docs.agent-actions.com/config/prompting",
        )
