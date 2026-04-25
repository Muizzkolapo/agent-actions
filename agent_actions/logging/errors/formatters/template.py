"""Template rendering error formatter."""

from difflib import SequenceMatcher
from typing import Any

from ..user_error import UserError
from .base import ErrorFormatter


class TemplateErrorFormatter(ErrorFormatter):
    """Handles template rendering errors with missing variables."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        exc_names = {type(exc).__name__, type(root).__name__}
        return "TemplateVariableError" in exc_names

    def format(
        self, exc: Exception, root: Exception, message: str, context: dict[str, Any]
    ) -> UserError:
        agent_name = context.get("agent") or context.get("agent_name") or "NOT_SET"
        missing = context.get("missing_variables", [])
        available = context.get("available_variables", [])

        # dict types aren't extracted by ErrorContextService
        namespace_context = getattr(exc, "namespace_context", {}) or {}
        storage_hints = getattr(exc, "storage_hints", {}) or {}

        details_lines: list[str] = [
            f"Template rendering failed for agent '{agent_name}'",
            "",
        ]

        for var in missing:
            details_lines.extend(
                self._format_variable_diagnostic(var, namespace_context, storage_hints)
            )

        if not missing:
            details_lines.append("  Unable to parse missing variable from error.")
            if namespace_context:
                namespaces = list(namespace_context.keys())
                details_lines.append(f"  Available namespaces: {', '.join(namespaces)}")

        hint = self._generate_hint(missing, namespace_context, storage_hints)

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
            docs_url="https://docs.runagac.com/config/prompting",
        )

    def _format_variable_diagnostic(
        self,
        var: str,
        namespace_context: dict[str, list[str]],
        storage_hints: dict[str, Any] | None = None,
    ) -> list[str]:
        """Format diagnostic information for a single missing variable."""
        lines: list[str] = []
        storage_hints = storage_hints or {}

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
                    display_fields = fields_in_ns[:10]
                    suffix = (
                        f" (and {len(fields_in_ns) - 10} more)" if len(fields_in_ns) > 10 else ""
                    )
                    lines.append(f"  Available in '{ns}': {', '.join(display_fields)}{suffix}")

                hint = storage_hints.get(var)
                if hint:
                    lines.append("")
                    lines.append(
                        f"  FOUND IN STORAGE: Field '{hint['field']}' exists in "
                        f"stored data for '{hint['namespace']}'"
                    )
                    lines.append(
                        f"    Storage has {hint['stored_count']} fields, but only "
                        f"{hint['loaded_count']} were loaded into template context."
                    )
                    lines.append(
                        "    The field was produced by the tool but not declared "
                        "in any upstream schema."
                    )

                suggestion = self._find_similar(field, fields_in_ns)
                if suggestion:
                    lines.append("")
                    lines.append(f"  Did you mean '{ns}.{suggestion}'?")
            else:
                if namespace_context:
                    namespaces = list(namespace_context.keys())
                    lines.append(f"  Available namespaces: {', '.join(namespaces)}")
        else:
            hint = storage_hints.get(var)
            if hint:
                ns = hint["namespace"]
                field = hint["field"]
                lines.append(f"  Reference: {ns}.{field}  (reported as '{var}')")
                lines.append(f"  Namespace '{ns}' exists: YES")
                lines.append(f"  Field '{field}' in namespace: NO")
                lines.append("")
                lines.append(
                    f"  FOUND IN STORAGE: Field '{field}' exists in stored data for '{ns}'"
                )
                lines.append(
                    f"    Storage has {hint['stored_count']} fields, but only "
                    f"{hint['loaded_count']} were loaded into template context."
                )
                lines.append(
                    "    The field was produced by the tool but not declared "
                    "in any upstream schema."
                )
            else:
                lines.append(f"  Missing variable: '{var}'")
            if namespace_context:
                namespaces = list(namespace_context.keys())
                lines.append(f"  Available namespaces: {', '.join(namespaces)}")

        lines.append("")  # Add blank line between variables
        return lines

    def _find_similar(
        self, target: str, candidates: list[str], threshold: float = 0.6
    ) -> str | None:
        """Find most similar field name using difflib."""
        best_match = None
        best_ratio = threshold
        for candidate in candidates:
            ratio = SequenceMatcher(None, target.lower(), candidate.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = candidate
        return best_match

    def _generate_hint(
        self,
        missing: list[str],
        namespace_context: dict[str, list[str]],
        storage_hints: dict[str, Any] | None = None,
    ) -> str:
        """Generate actionable hint based on error type."""
        if not missing:
            return "Check template syntax."

        storage_hints = storage_hints or {}

        # Use first missing var for hint — a single actionable suggestion is
        # clearer than listing all missing variables.
        var = missing[0]
        # Check storage hints first (works for both dotted and leaf-only vars)
        if var in storage_hints:
            field = storage_hints[var]["field"]
            return (
                f"Add a schema to the action that produces this field:\n"
                f"  schema:\n"
                f"    {field}: <type>"
            )
        if "." in var:
            ns, _field = var.split(".", 1)
            if ns not in namespace_context:
                return (
                    f"Namespace '{ns}' is not declared in context_scope.observe. "
                    f"Add '{ns}.*' or specific fields to context_scope.observe in your workflow config."
                )
            return f"Check that '{ns}' produces the referenced field."
        return "Check that the variable is defined in context_scope."
