"""Base error formatter interface for Strategy Pattern."""

from abc import ABC, abstractmethod
from typing import Dict, Any
from ..user_error import UserError


class ErrorFormatter(ABC):
    """
    Base error formatter strategy.

    Each concrete formatter handles a specific category of errors
    (Configuration, Model, Authentication, File, API, etc.).
    """

    @abstractmethod
    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        """
        Determine if this formatter can handle the given error.

        Args:
            exc: The original exception
            root: The root cause exception
            message: The root cause error message

        Returns:
            True if this formatter should handle the error
        """
        pass

    @abstractmethod
    def format(
        self,
        exc: Exception,
        root: Exception,
        message: str,
        context: Dict[str, Any]
    ) -> UserError:
        """
        Format the error into a user-friendly UserError.

        Args:
            exc: The original exception
            root: The root cause exception
            message: The root cause error message
            context: Additional context (agent, file_path, etc.)

        Returns:
            UserError with user-friendly message
        """
        pass
