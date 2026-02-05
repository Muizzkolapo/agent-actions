"""Pre-flight validation errors for unified batch/online error handling.

This module provides error classes specifically for pre-flight validation,
ensuring consistent error messages between batch and online execution modes.
"""
# Unnecessary-pass: Simple exception classes inherit all behavior from parent

from typing import Any, Dict, List, Optional

from agent_actions.errors.base import AgentActionsError


class PreFlightValidationError(AgentActionsError):
    """Base exception for all pre-flight validation errors.

    Pre-flight validation runs before any LLM calls to catch configuration
    and input errors early, with consistent messaging across batch/online modes.

    Args:
        message: The error message
        available_references: List of available context references
        missing_references: List of missing/invalid references
        hint: Actionable suggestion for fixing the error
        mode: Execution mode ('batch' or 'online')
        agent_name: Name of the agent being validated
        context: Additional context dict
        cause: Original exception
    """

    def __init__(
        self,
        message: str,
        *,
        available_references: Optional[List[str]] = None,
        missing_references: Optional[List[str]] = None,
        hint: Optional[str] = None,
        mode: Optional[str] = None,
        agent_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        ctx = context or {}
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

        # Store as instance attributes for easy access
        self.available_references = available_references or []
        self.missing_references = missing_references or []
        self.hint = hint
        self.mode = mode
        self.agent_name = agent_name

    def __str__(self) -> str:
        """Return user-friendly string representation instead of raw context dump."""
        return self.format_user_message()

    def format_user_message(self) -> str:
        """Format a user-friendly error message with all details."""
        lines = [self.args[0]]  # Just the message, no class name prefix
        lines.append("")

        if self.missing_references:
            lines.append(f"  Missing: {', '.join(self.missing_references)}")
        if self.available_references:
            # Truncate available references for readability
            refs = self.available_references
            if len(refs) > 10:
                display_refs = refs[:10] + [f"(+{len(refs) - 10} more)"]
            else:
                display_refs = refs
            lines.append(f"  Available: {', '.join(display_refs)}")

        if self.hint:
            lines.append("")
            lines.append(f"  Hint: {self.hint}")

        if self.mode or self.agent_name:
            lines.append("")
            if self.agent_name:
                lines.append(f"  Agent: {self.agent_name}")
            if self.mode:
                lines.append(f"  Mode: {self.mode}")

        return "\n".join(lines)


class VendorConfigError(PreFlightValidationError):
    """Raised when vendor configuration is invalid or incompatible.

    Args:
        message: Description of the vendor config issue
        vendor: Name of the vendor (openai, anthropic, etc.)
        missing_fields: List of required fields that are missing
        unsupported_features: List of features requested but not supported
        agent_name: Name of the agent being validated
        mode: Execution mode ('batch' or 'online')
        context: Additional context dict
        cause: Original exception
    """

    def __init__(
        self,
        message: str,
        *,
        vendor: Optional[str] = None,
        missing_fields: Optional[List[str]] = None,
        unsupported_features: Optional[List[str]] = None,
        agent_name: Optional[str] = None,
        mode: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        ctx = context or {}
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
        expected_fields: Optional[List[str]] = None,
        actual_fields: Optional[List[str]] = None,
        agent_name: Optional[str] = None,
        mode: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        ctx = context or {}
        if expected_fields is not None:
            ctx["expected_fields"] = expected_fields
        if actual_fields is not None:
            ctx["actual_fields"] = actual_fields

        hint = None
        missing_list: Optional[List[str]] = None
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
    """Raised when file or directory paths are invalid or inaccessible.

    Args:
        message: Description of the path issue
        invalid_paths: List of paths that are invalid or inaccessible
        path_type: Type of path ('file', 'directory', 'input', 'output', 'schema')
        agent_name: Name of the agent being validated
        mode: Execution mode ('batch' or 'online')
        context: Additional context dict
        cause: Original exception
    """

    def __init__(
        self,
        message: str,
        *,
        invalid_paths: Optional[List[str]] = None,
        path_type: Optional[str] = None,
        agent_name: Optional[str] = None,
        mode: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        ctx = context or {}
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
