"""
Unified error formatter for pre-flight validation.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ValidationIssue:
    """Represents a single validation issue (error or warning).

    Attributes:
        message: The main error/warning message
        issue_type: Type of issue ('error', 'warning')
        category: Category of the issue ('template', 'context', 'dependency', etc.)
        missing_refs: List of missing references/fields
        available_refs: List of available references/fields
        hint: Actionable suggestion for fixing the issue
        agent_name: Name of the agent where issue occurred
        location: Location info (e.g., template line number)
        extra_context: Additional context information
    """

    message: str
    issue_type: str = "error"
    category: str = "general"
    missing_refs: List[str] = field(default_factory=list)
    available_refs: List[str] = field(default_factory=list)
    hint: Optional[str] = None
    agent_name: Optional[str] = None
    location: Optional[str] = None
    extra_context: Dict[str, Any] = field(default_factory=dict)


class PreFlightErrorFormatter:
    """Formats pre-flight validation errors consistently.

    This formatter ensures that both batch and online modes produce
    identical, user-friendly error messages.
    """

    @staticmethod
    def format_issue(issue: ValidationIssue, mode: str = "unknown") -> str:
        """Format a single validation issue into a user-friendly string.

        Args:
            issue: The validation issue to format
            mode: Execution mode ('batch' or 'online')

        Returns:
            Formatted error string
        """
        lines = []

        # Header with issue type and category
        type_label = "ERROR" if issue.issue_type == "error" else "WARNING"
        lines.append(f"[{type_label}] {issue.message}")
        lines.append("")

        # Missing and available references
        if issue.missing_refs:
            lines.append(f"  Missing: {', '.join(issue.missing_refs)}")
        if issue.available_refs:
            # Limit to reasonable number for display
            refs_display = issue.available_refs[:10]
            if len(issue.available_refs) > 10:
                refs_display.append(f"... (+{len(issue.available_refs) - 10} more)")
            lines.append(f"  Available: {', '.join(refs_display)}")

        # Hint
        if issue.hint:
            lines.append("")
            lines.append(f"  Hint: {issue.hint}")

        # Context section
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
    def format_issues(issues: List[ValidationIssue], mode: str = "unknown") -> str:
        """Format multiple validation issues into a summary string.

        Args:
            issues: List of validation issues
            mode: Execution mode ('batch' or 'online')

        Returns:
            Formatted summary string
        """
        if not issues:
            return "Pre-flight validation passed with no issues."

        errors = [i for i in issues if i.issue_type == "error"]
        warnings = [i for i in issues if i.issue_type == "warning"]

        lines = []

        # Summary header
        lines.append("Pre-flight Validation Failed")
        lines.append(f"  {len(errors)} error(s), {len(warnings)} warning(s)")
        lines.append("")

        # Format errors first
        if errors:
            lines.append("Errors:")
            lines.append("-" * 50)
            for i, error in enumerate(errors, 1):
                lines.append(f"\n{i}. {PreFlightErrorFormatter.format_issue(error, mode)}")

        # Then warnings
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
        missing_fields: Optional[List[str]] = None,
        unsupported_features: Optional[List[str]] = None,
        agent_name: Optional[str] = None,
    ) -> ValidationIssue:
        """Create a validation issue for vendor configuration problems.

        Args:
            message: Description of the vendor config issue
            vendor: Name of the vendor
            missing_fields: Required fields that are missing
            unsupported_features: Features not supported by vendor
            agent_name: Name of the agent

        Returns:
            ValidationIssue configured for vendor config errors
        """
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
        invalid_paths: List[str],
        path_type: str = "file",
        agent_name: Optional[str] = None,
    ) -> ValidationIssue:
        """Create a validation issue for invalid paths.

        Args:
            message: Description of the path issue
            invalid_paths: List of invalid paths
            path_type: Type of path ('file', 'directory', etc.)
            agent_name: Name of the agent

        Returns:
            ValidationIssue configured for path errors
        """
        return ValidationIssue(
            message=message,
            issue_type="error",
            category="path",
            missing_refs=invalid_paths,
            hint=f"Verify these {path_type}(s) exist: {', '.join(invalid_paths)}",
            agent_name=agent_name,
            extra_context={"path_type": path_type},
        )
