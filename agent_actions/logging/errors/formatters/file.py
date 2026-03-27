"""File operation error formatter."""

from typing import Any

from ..user_error import UserError
from .base import ErrorFormatter


class FileErrorFormatter(ErrorFormatter):
    """Handles file-related errors."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        exc_names = [type(exc).__name__, type(root).__name__]

        file_error_types = ["FileNotFoundError", "PermissionError", "FileLoadError"]
        if any(name in file_error_types for name in exc_names):
            return True

        message_lower = message.lower()
        file_patterns = [
            "file not found",
            "no such file",
            "permission denied",
            "cannot read",
            "cannot write",
        ]
        return any(pattern in message_lower for pattern in file_patterns)

    def format(
        self, exc: Exception, root: Exception, message: str, context: dict[str, Any]
    ) -> UserError:
        if "not found" in message.lower():
            file_path = context.get("file_path", "unknown")
            agent = context.get("agent")

            if agent and file_path == "unknown":
                return UserError(
                    category="File Error",
                    title="Agent configuration not found",
                    details=f"Could not find configuration for agent '{agent}'",
                    fix=(
                        f"1. Create agents/{agent}.yaml\n"
                        "     2. Or use an existing agent: "
                        "agac run --agent <existing-agent>"
                    ),
                    context=context,
                    docs_url="https://docs.runagac.com/agents/create",
                )

            return UserError(
                category="File Error",
                title="File not found",
                details=f"Could not find file: {file_path}",
                fix="Ensure the file exists and the path is correct",
                context=context,
            )

        return UserError(
            category="File Error",
            title="File operation failed",
            details=message,
            fix="Check file permissions and paths",
            context=context,
        )
