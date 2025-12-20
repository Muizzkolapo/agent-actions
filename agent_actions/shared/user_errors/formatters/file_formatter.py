"""File operation error formatter."""

from typing import Dict, Any
from .error_formatter_base import ErrorFormatter
from ..user_error import UserError


class FileErrorFormatter(ErrorFormatter):
    """Handles file-related errors."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        """Detect file-related errors."""
        exc_names = [type(exc).__name__, type(root).__name__]

        # Check exception types
        file_error_types = ['FileNotFoundError', 'PermissionError', 'FileLoadError']
        if any(name in file_error_types for name in exc_names):
            return True

        message_lower = message.lower()
        file_patterns = [
            'file not found',
            'no such file',
            'permission denied',
            'cannot read',
            'cannot write'
        ]
        return any(pattern in message_lower for pattern in file_patterns)

    def format(
        self,
        exc: Exception,
        root: Exception,
        message: str,
        context: Dict[str, Any]
    ) -> UserError:
        """Handle file-related errors."""
        if 'not found' in message.lower():
            file_path = context.get('file_path', 'unknown')
            agent = context.get('agent')

            if agent and file_path == 'unknown':
                # Probably missing agent config
                return UserError(
                    category="File Error",
                    title="Agent configuration not found",
                    details=f"Could not find configuration for agent '{agent}'",
                    fix=(
                        f"1. Create agents/{agent}.yaml\n"
                        "     2. Or use an existing agent: "
                        "agent-actions run --agent <existing-agent>"
                    ),
                    context=context,
                    docs_url="https://docs.agent-actions.com/agents/create"
                )

            return UserError(
                category="File Error",
                title="File not found",
                details=f"Could not find file: {file_path}",
                fix="Ensure the file exists and the path is correct",
                context=context
            )

        # Generic file error
        return UserError(
            category="File Error",
            title="File operation failed",
            details=message,
            fix="Check file permissions and paths",
            context=context
        )
