"""Error context extraction and merging service."""

from typing import Dict, Any, Optional


class ErrorContextService:
    """Handles error context extraction and merging from exceptions."""

    @staticmethod
    def merge_exception_context(
        exc: Exception,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Merge exception context with additional context.

        Extracts context from exception attributes and merges with
        any additional context provided. Additional context takes precedence.

        Args:
            exc: The exception to extract context from
            additional_context: Optional additional context dict

        Returns:
            Merged context dictionary
        """
        merged_context = {}

        # Extract exception.context if available
        if hasattr(exc, 'context') and isinstance(exc.context, dict):
            merged_context.update(exc.context)

        # Extract other useful exception attributes
        for attr_name in dir(exc):
            if not attr_name.startswith('_') and attr_name not in ['args', 'with_traceback', 'context']:
                try:
                    attr_value = getattr(exc, attr_name)
                    # Only include simple types (not methods/callables)
                    if not callable(attr_value) and isinstance(
                        attr_value,
                        (str, int, float, bool, type(None))
                    ):
                        merged_context[attr_name] = attr_value
                except Exception:
                    pass  # Skip attributes that can't be accessed

        # Additional context takes precedence
        if additional_context:
            merged_context.update(additional_context)

        return merged_context
