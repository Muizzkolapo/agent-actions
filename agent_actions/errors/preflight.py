"""Pre-flight validation errors for unified batch/online error handling."""

from typing import Any

from agent_actions.errors.base import AgentActionsError


def _render_sections(
    header: str,
    sections: list,
    *,
    truncate_lists_at: int = 10,
) -> str:
    """Render a multi-section error message from (label, value) pairs.

    Sections: None=group separator, str=raw line, (label, value)=formatted pair.
    List values are comma-joined and truncated at truncate_lists_at.
    """
    lines = [header]

    # Split sections into groups at None boundaries
    groups: list[list] = [[]]
    for item in sections:
        if item is None:
            groups.append([])
        else:
            groups[-1].append(item)

    for group in groups:
        group_lines: list[str] = []
        for item in group:
            if isinstance(item, str):
                group_lines.append(item)
            else:
                label, value = item
                if value is None:
                    continue
                if isinstance(value, list):
                    if not value:
                        continue
                    display = list(value)
                    if len(display) > truncate_lists_at:
                        display = display[:truncate_lists_at] + [
                            f"(+{len(display) - truncate_lists_at} more)"
                        ]
                    group_lines.append(f"  {label}: {', '.join(str(v) for v in display)}")
                else:
                    group_lines.append(f"  {label}: {value}")
        if group_lines:
            lines.append("")
            lines.extend(group_lines)

    return "\n".join(lines)


class PreFlightValidationError(AgentActionsError):
    """Base exception for all pre-flight validation errors."""

    def __init__(
        self,
        message: str,
        *,
        available_references: list[str] | None = None,
        missing_references: list[str] | None = None,
        hint: str | None = None,
        mode: str | None = None,
        agent_name: str | None = None,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        ctx = dict(context) if context else {}
        if available_references is not None:
            ctx["available_references"] = available_references
        if missing_references is not None:
            ctx["missing_references"] = missing_references
        if hint is not None:
            ctx["hint"] = hint
        if mode is not None:
            ctx["mode"] = mode
        if agent_name is not None:
            ctx["agent_name"] = agent_name

        super().__init__(message, context=ctx, cause=cause)
        self.available_references = available_references or []
        self.missing_references = missing_references or []
        self.hint = hint
        self.mode = mode
        self.agent_name = agent_name

    def __str__(self) -> str:
        return self.format_user_message()

    def format_user_message(self) -> str:
        return _render_sections(
            self.args[0],
            [
                None,
                ("Missing", self.missing_references or None),
                ("Available", self.available_references or None),
                None,
                ("Hint", self.hint),
                None,
                ("Agent", self.agent_name),
                ("Mode", self.mode),
            ],
        )


class VendorConfigError(PreFlightValidationError):
    """Raised when vendor configuration is invalid or incompatible."""

    def __init__(
        self,
        message: str,
        *,
        vendor: str | None = None,
        missing_fields: list[str] | None = None,
        unsupported_features: list[str] | None = None,
        agent_name: str | None = None,
        mode: str | None = None,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        ctx = dict(context) if context else {}
        if vendor is not None:
            ctx["vendor"] = vendor
        if unsupported_features is not None:
            ctx["unsupported_features"] = unsupported_features

        hint_parts = []
        if missing_fields:
            hint_parts.append(f"Add required fields: {', '.join(missing_fields)}")
        if unsupported_features:
            hint_parts.append(f"Remove unsupported features: {', '.join(unsupported_features)}")
        hint = " ".join(hint_parts) if hint_parts else None

        super().__init__(
            message,
            missing_references=missing_fields,
            hint=hint,
            mode=mode,
            agent_name=agent_name,
            context=ctx,
            cause=cause,
        )

        self.vendor = vendor
        self.missing_fields = missing_fields or []
        self.unsupported_features = unsupported_features or []


class ContextStructureError(PreFlightValidationError):
    """Raised when context data structure doesn't match expected schema."""

    def __init__(
        self,
        message: str,
        *,
        expected_fields: list[str] | None = None,
        actual_fields: list[str] | None = None,
        agent_name: str | None = None,
        mode: str | None = None,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        ctx = dict(context) if context else {}
        if expected_fields is not None:
            ctx["expected_fields"] = expected_fields
        if actual_fields is not None:
            ctx["actual_fields"] = actual_fields

        hint = None
        missing_list: list[str] | None = None
        if expected_fields and actual_fields is not None:
            # actual_fields=[] means "known empty" — compute the real diff
            missing = sorted(set(expected_fields) - set(actual_fields))
            missing_list = missing if missing else None
            if missing:
                hint = f"Missing required fields: {', '.join(missing)}"
        elif expected_fields:
            # actual_fields=None means "unknown" — assume all expected are missing
            missing_list = expected_fields

        super().__init__(
            message,
            missing_references=missing_list,
            available_references=actual_fields if actual_fields else None,
            hint=hint,
            mode=mode,
            agent_name=agent_name,
            context=ctx,
            cause=cause,
        )

        self.expected_fields = expected_fields or []
        self.actual_fields = actual_fields or []


class PathValidationError(PreFlightValidationError):
    """Raised when file or directory paths are invalid or inaccessible."""

    def __init__(
        self,
        message: str,
        *,
        invalid_paths: list[str] | None = None,
        path_type: str | None = None,
        agent_name: str | None = None,
        mode: str | None = None,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        ctx = dict(context) if context else {}
        if path_type is not None:
            ctx["path_type"] = path_type

        hint = None
        if invalid_paths:
            hint = (
                f"Verify the following paths exist and are accessible: {', '.join(invalid_paths)}"
            )

        super().__init__(
            message,
            missing_references=invalid_paths,
            hint=hint,
            mode=mode,
            agent_name=agent_name,
            context=ctx,
            cause=cause,
        )

        self.invalid_paths = invalid_paths or []
        self.path_type = path_type
