"""Template rendering error formatter."""

from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

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
        missing = context.get("missing_variables", [])
        available = context.get("available_variables", [])

        # Get namespace_context from exception (dict types aren't extracted by ErrorContextService)
        namespace_context = getattr(exc, "namespace_context", {}) or {}

        details_lines: List[str] = [
            f"Template rendering failed for agent '{agent_name}'",
            "",
        ]

        for var in missing:
            details_lines.extend(self._format_variable_diagnostic(var, namespace_context))

        # If no missing variables were parsed, show generic message with available info
        if not missing:
            details_lines.append("  Unable to parse missing variable from error.")
            if namespace_context:
                namespaces = list(namespace_context.keys())
                details_lines.append(f"  Available namespaces: {', '.join(namespaces)}")

        # Generate hint based on error type
        hint = self._generate_hint(missing, namespace_context)

        return UserError(
            category="Template Error",
            title="Template rendering failed",
            details="\n".join(details_lines),
            fix=hint,
            context={
                "agent": agent_name,
                "missing_variables": missing,
                "available_variables": available,
                "template_line": context.get("template_line"),
                "mode": context.get("mode"),
            },
            docs_url="https://docs.agent-actions.com/config/prompting",
        )

    def _format_variable_diagnostic(
        self, var: str, namespace_context: Dict[str, List[str]]
    ) -> List[str]:
        """Format diagnostic information for a single missing variable."""
        lines: List[str] = []

        if "." in var:
            ns, field = var.split(".", 1)
            ns_exists = ns in namespace_context
            fields_in_ns = namespace_context.get(ns, [])
            field_exists = field in fields_in_ns

            lines.append(f"  Reference: {var}")
            lines.append(f"  Namespace '{ns}' exists: {'YES' if ns_exists else 'NO'}")

            if ns_exists:
                lines.append(f"  Field '{field}' in namespace: {'YES' if field_exists else 'NO'}")
                if fields_in_ns:
                    # Show up to 10 fields
                    display_fields = fields_in_ns[:10]
                    suffix = (
                        f" (and {len(fields_in_ns) - 10} more)" if len(fields_in_ns) > 10 else ""
                    )
                    lines.append(f"  Available in '{ns}': {', '.join(display_fields)}{suffix}")

                # Suggest similar field
                suggestion = self._find_similar(field, fields_in_ns)
                if suggestion:
                    lines.append("")
                    lines.append(f"  Did you mean '{ns}.{suggestion}'?")
            else:
                # Namespace doesn't exist - show available namespaces
                if namespace_context:
                    namespaces = list(namespace_context.keys())
                    lines.append(f"  Available namespaces: {', '.join(namespaces)}")
        else:
            # Top-level variable (no namespace)
            lines.append(f"  Missing variable: '{var}'")
            if namespace_context:
                namespaces = list(namespace_context.keys())
                lines.append(f"  Available namespaces: {', '.join(namespaces)}")

        lines.append("")  # Add blank line between variables
        return lines

    def _find_similar(
        self, target: str, candidates: List[str], threshold: float = 0.6
    ) -> Optional[str]:
        """Find most similar field name using difflib."""
        best_match = None
        best_ratio = threshold
        for candidate in candidates:
            ratio = SequenceMatcher(None, target.lower(), candidate.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = candidate
        return best_match

    def _generate_hint(self, missing: List[str], namespace_context: Dict[str, List[str]]) -> str:
        """Generate actionable hint based on error type."""
        if not missing:
            return "Check template syntax."

        var = missing[0]
        if "." in var:
            ns, _ = var.split(".", 1)
            if ns not in namespace_context:
                return f"Add '{ns}' to dependencies or check action name spelling."
            return f"Check that '{ns}' produces the referenced field."
        return "Check that the variable is defined in context_scope."
