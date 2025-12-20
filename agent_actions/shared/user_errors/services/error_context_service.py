"""Error context extraction and merging service."""

from typing import Dict, Any, Optional


class ErrorContextService:  # pylint: disable=too-few-public-methods
    """
    Handles error context extraction and merging from exceptions.

    Utility class - single public method by design (merge_exception_context).
    """

    @staticmethod
    def merge_exception_context(
        exc: Exception,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Merge exception context from entire exception chain.

        Traverses the complete exception chain (via __cause__ and __context__)
        and merges context from all exceptions. Root cause context is merged first,
        then intermediate exceptions, then the outermost exception. This ensures
        that more specific (outer) contexts override more general (inner) ones
        while preserving all available information.

        Args:
            exc: The exception to extract context from
            additional_context: Optional additional context dict

        Returns:
            Merged context dictionary with context from entire exception chain
        """
        merged_context = {}

        # Build exception chain from outermost to root
        chain = []
        current = exc
        visited = set()

        while current and id(current) not in visited:
            visited.add(id(current))
            chain.append(current)
            # Check __cause__ first (explicit chaining), then __context__ (implicit)
            current = getattr(current, '__cause__', None) or getattr(current, '__context__', None)

        # Merge contexts: root first, then up the chain
        # Outer contexts override inner ones for same keys
        for exception in reversed(chain):
            if hasattr(exception, 'context') and isinstance(exception.context, dict):
                merged_context.update(exception.context)

        # Extract other useful exception attributes from outermost exception only
        # (to avoid attribute conflicts from different exception types in chain)
        excluded_attrs = ['args', 'with_traceback', 'context']
        for attr_name in dir(exc):
            if not attr_name.startswith('_') and attr_name not in excluded_attrs:
                try:
                    attr_value = getattr(exc, attr_name)
                    # Only include simple types (not methods/callables)
                    if not callable(attr_value) and isinstance(
                        attr_value,
                        (str, int, float, bool, type(None))
                    ):
                        merged_context[attr_name] = attr_value
                except Exception:  # pylint: disable=broad-exception-caught
                    # Silently skip attributes that can't be accessed - defensive programming
                    pass

        # Additional context takes final precedence
        if additional_context:
            merged_context.update(additional_context)

        return merged_context
