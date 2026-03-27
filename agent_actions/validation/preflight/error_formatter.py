"""Unified error formatter for pre-flight validation."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationIssue:
    """Represents a single validation issue (error or warning)."""

    message: str
    issue_type: str = "error"
    category: str = "general"
    missing_refs: list[str] = field(default_factory=list)
    available_refs: list[str] = field(default_factory=list)
    hint: str | None = None
    agent_name: str | None = None
    location: str | None = None
    extra_context: dict[str, Any] = field(default_factory=dict)


class PreFlightErrorFormatter:
    """Formats pre-flight validation errors consistently."""

    @staticmethod
    def format_issue(issue: ValidationIssue, mode: str = "unknown") -> str:
        """Format a single validation issue into a user-friendly string."""
        lines = []

        type_label = "ERROR" if issue.issue_type == "error" else "WARNING"
        lines.append(f"[{type_label}] {issue.message}")
        lines.append("")

        if issue.missing_refs:
            lines.append(f"  Missing: {', '.join(issue.missing_refs)}")
        if issue.available_refs:
            refs_display = issue.available_refs[:10]
            if len(issue.available_refs) > 10:
                refs_display.append(f"... (+{len(issue.available_refs) - 10} more)")
            lines.append(f"  Available: {', '.join(refs_display)}")

        if issue.hint:
            lines.append("")
            lines.append(f"  Hint: {issue.hint}")

        context_items = []
        if mode != "unknown":
            context_items.append(f"mode: {mode}")
        if issue.agent_name:
            context_items.append(f"agent: {issue.agent_name}")
        if issue.location:
            context_items.append(f"location: {issue.location}")
        if issue.category != "general":
            context_items.append(f"category: {issue.category}")

        if context_items:
            lines.append("")
            lines.append("  Context:")
            for item in context_items:
                lines.append(f"    {item}")

        return "\n".join(lines)

    @staticmethod
    def format_issues(issues: list[ValidationIssue], mode: str = "unknown") -> str:
        """Format multiple validation issues into a summary string."""
        if not issues:
            return "Pre-flight validation passed with no issues."

        errors = [i for i in issues if i.issue_type == "error"]
        warnings = [i for i in issues if i.issue_type == "warning"]

        lines = []

        lines.append("Pre-flight Validation Failed")
        lines.append(f"  {len(errors)} error(s), {len(warnings)} warning(s)")
        lines.append("")

        if errors:
            lines.append("Errors:")
            lines.append("-" * 50)
            for i, error in enumerate(errors, 1):
                lines.append(f"\n{i}. {PreFlightErrorFormatter.format_issue(error, mode)}")

        if warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.append("-" * 50)
            for i, warning in enumerate(warnings, 1):
                lines.append(f"\n{i}. {PreFlightErrorFormatter.format_issue(warning, mode)}")

        return "\n".join(lines)

    @staticmethod
    def create_vendor_config_issue(
        message: str,
        vendor: str,
        missing_fields: list[str] | None = None,
        unsupported_features: list[str] | None = None,
        agent_name: str | None = None,
    ) -> ValidationIssue:
        """Create a ValidationIssue for vendor configuration problems."""
        hint_parts = []
        if missing_fields:
            hint_parts.append(f"Add required fields: {', '.join(missing_fields)}")
        if unsupported_features:
            hint_parts.append(f"Remove unsupported features: {', '.join(unsupported_features)}")

        return ValidationIssue(
            message=message,
            issue_type="error",
            category="vendor",
            missing_refs=missing_fields or [],
            hint=" ".join(hint_parts) if hint_parts else None,
            agent_name=agent_name,
            extra_context={
                "vendor": vendor,
                "unsupported_features": unsupported_features or [],
            },
        )

    @staticmethod
    def create_path_issue(
        message: str,
        invalid_paths: list[str],
        path_type: str = "file",
        agent_name: str | None = None,
    ) -> ValidationIssue:
        """Create a ValidationIssue for invalid paths."""
        return ValidationIssue(
            message=message,
            issue_type="error",
            category="path",
            missing_refs=invalid_paths,
            hint=f"Verify these {path_type}(s) exist: {', '.join(invalid_paths)}",
            agent_name=agent_name,
            extra_context={"path_type": path_type},
        )
