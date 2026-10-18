"""Error classes for static type checking."""

from collections.abc import Collection
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorSeverity(Enum):
    """Severity level for static type errors."""

    ERROR = "error"  # Blocks execution
    WARNING = "warning"  # Informational, doesn't block


@dataclass
class FieldLocation:
    """Location of a field reference in config."""

    agent_name: str
    config_field: str  # 'prompt', 'guard', 'context_scope.observe', etc.
    line_number: int | None = None
    raw_reference: str = ""


@dataclass
class StaticTypeIssue:
    """Base class for static type checking issues."""

    message: str
    severity: ErrorSeverity
    location: FieldLocation
    referenced_agent: str
    referenced_field: str
    available_fields: set[str] = field(default_factory=set)
    hint: str | None = None

    def format_message(self) -> str:
        """Format error for display."""
        prefix = "StaticTypeError" if self.severity == ErrorSeverity.ERROR else "StaticTypeWarning"
        lines = [
            f"{prefix}: {self.message}",
            "",
            f"  Action: {self.location.agent_name}",
            f"  Reference: {self.location.raw_reference}",
            f"  Location: {self.location.config_field}",
        ]

        if self.available_fields:
            fields_str = ", ".join(sorted(self.available_fields))
            lines.append(f"  Available fields in '{self.referenced_agent}': {fields_str}")

        if self.hint:
            lines.append("")
            lines.append(f"  Hint: {self.hint}")

        return "\n".join(lines)


class StaticTypeError(StaticTypeIssue):
    """Blocking error that prevents workflow execution."""

    def __init__(
        self,
        message: str,
        location: FieldLocation,
        referenced_agent: str,
        referenced_field: str,
        available_fields: set[str] | None = None,
        hint: str | None = None,
    ):
        super().__init__(
            message=message,
            severity=ErrorSeverity.ERROR,
            location=location,
            referenced_agent=referenced_agent,
            referenced_field=referenced_field,
            available_fields=available_fields or set(),
            hint=hint,
        )


class StaticTypeWarning(StaticTypeIssue):
    """Non-blocking warning that doesn't prevent execution."""

    def __init__(
        self,
        message: str,
        location: FieldLocation,
        referenced_agent: str,
        referenced_field: str,
        available_fields: set[str] | None = None,
        hint: str | None = None,
    ):
        super().__init__(
            message=message,
            severity=ErrorSeverity.WARNING,
            location=location,
            referenced_agent=referenced_agent,
            referenced_field=referenced_field,
            available_fields=available_fields or set(),
            hint=hint,
        )


class StaticValidationResult:
    """Aggregated result of static type checking."""

    def __init__(self) -> None:
        self.errors: list[StaticTypeError] = []
        self.warnings: list[StaticTypeWarning] = []
        self._strict_mode = False

    @property
    def is_valid(self) -> bool:
        """Returns True if no blocking errors exist."""
        if self._strict_mode:
            return len(self.errors) == 0 and len(self.warnings) == 0
        return len(self.errors) == 0

    def add_error(self, error: StaticTypeError) -> None:
        """Add a blocking error."""
        self.errors.append(error)

    def add_warning(self, warning: StaticTypeWarning) -> None:
        """Add a non-blocking warning."""
        self.warnings.append(warning)

    def set_strict_mode(self, strict: bool = True) -> None:
        """Enable strict mode where warnings are treated as errors."""
        self._strict_mode = strict

    def format_report(self) -> str:
        """Format full validation report."""
        lines = ["=" * 80]
        lines.append("STATIC TYPE CHECKING RESULTS")
        lines.append("=" * 80)

        if not self.errors and not self.warnings:
            lines.append("")
            lines.append("  All field references validated successfully.")
            lines.append("")
        else:
            by_agent: dict[str, list[StaticTypeIssue]] = {}
            for issue in self.errors + self.warnings:
                agent = issue.location.agent_name
                if agent not in by_agent:
                    by_agent[agent] = []
                by_agent[agent].append(issue)

            for agent, agent_issues in sorted(by_agent.items()):
                lines.append("")
                lines.append(f"Action: '{agent}'")
                lines.append("-" * 60)
                for issue in agent_issues:  # type: ignore[assignment]
                    icon = "X" if issue.severity == ErrorSeverity.ERROR else "!"
                    lines.append(f"  [{icon}] {issue.format_message()}")
                    lines.append("")

        lines.append("=" * 80)

        error_count = len(self.errors)
        warning_count = len(self.warnings)

        lines.append(f"Total: {error_count} error(s), {warning_count} warning(s)")
        lines.append("")

        return "\n".join(lines)

    def raise_if_invalid(self) -> None:
        """Raise PreFlightValidationError if validation failed."""
        if not self.is_valid:
            from agent_actions.errors.preflight import PreFlightValidationError

            raise PreFlightValidationError(
                self.format_report(),
                hint="Fix the static type errors above before running the workflow.",
            )

    def merge(self, other: "StaticValidationResult") -> None:
        """Merge another result into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for JSON serialization."""
        return {
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [
                {
                    "message": e.message,
                    "agent": e.location.agent_name,
                    "reference": e.location.raw_reference,
                    "location": e.location.config_field,
                    "referenced_agent": e.referenced_agent,
                    "referenced_field": e.referenced_field,
                    "available_fields": list(e.available_fields),
                    "hint": e.hint,
                }
                for e in self.errors
            ],
            "warnings": [
                {
                    "message": w.message,
                    "agent": w.location.agent_name,
                    "reference": w.location.raw_reference,
                    "available_fields": list(w.available_fields),
                    "hint": w.hint,
                }
                for w in self.warnings
            ],
        }


def read_through_reserved_name(
    name: str, written: str, field_path: str, action_names: Collection[str]
) -> tuple[str, str]:
    """What is wrong with a read through a name in ``RESERVED_NAMES_NO_RECORD_HAS``, and the fix.

    ``field_path`` is what follows the name; empty or ``*`` when the name is read whole.
    `action.<name>.<field>` drops the prefix; `action.<field>` copies the docs'
    placeholder, so the fix names the action in its place.
    """
    if name == "action":
        problem = f"reads '{written}', but there is no 'action' namespace"
        head, _, rest = field_path.partition(".")
        if head in action_names or (rest and head != "*"):
            fix = (
                f"Write '{written.replace('action.', '', 1)}': an upstream action's fields "
                f"are read under that action's own name."
            )
        elif head and head != "*":
            fix = (
                f"Write '{written.replace('action.', '<action name>.', 1)}', naming the "
                f"upstream action whose field it reads."
            )
        else:
            fix = "Read an upstream action's fields under that action's own name: producer.field."
        return problem, fix
    problem = f"reads '{written}', but '{name}' is a reserved name, not a namespace"
    fix = (
        "Read an upstream action's fields under that action's own name (producer.field), "
        "the input record under 'source' and seed data under 'seed'."
    )
    return problem, fix
