"""Error context extraction and merging service."""

from typing import Any


class ErrorContextService:
    """Handles error context extraction and merging from exception chains."""

    @staticmethod
    def merge_exception_context(
        exc: Exception, additional_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Merge context from the entire exception chain; outer overrides inner."""
        merged_context = {}

        chain = []
        current: Exception | None = exc
        visited = set()

        while current and id(current) not in visited:
            visited.add(id(current))
            chain.append(current)
            current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)

        for exception in reversed(chain):
            if hasattr(exception, "context") and isinstance(exception.context, dict):
                merged_context.update(exception.context)

        excluded_attrs = ["args", "with_traceback", "context"]
        for attr_name in dir(exc):
            if not attr_name.startswith("_") and attr_name not in excluded_attrs:
                try:
                    attr_value = getattr(exc, attr_name)
                    if not callable(attr_value) and isinstance(
                        attr_value, (str, int, float, bool, type(None))
                    ):
                        merged_context[attr_name] = attr_value
                except Exception:
                    pass

        if additional_context:
            merged_context.update(additional_context)

        return merged_context
