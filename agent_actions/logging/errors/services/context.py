"""Error context extraction and merging service."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ErrorContextService:
    """Handles error context extraction and merging from exception chains."""

    @staticmethod
    def merge_exception_context(
        exc: Exception, additional_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Merge context from the exception chain, outer over inner.

        *additional_context* fills only keys the exception leaves unset or ``None``; a
        ``None`` in it is never added.
        """
        merged_context = {}

        chain = []
        current: Exception | None = exc
        visited = set()

        while current and id(current) not in visited:
            visited.add(id(current))
            chain.append(current)
            cause = getattr(current, "__cause__", None)
            if cause is not None:
                current = cause
            elif getattr(current, "__suppress_context__", False):
                current = None
            else:
                current = getattr(current, "__context__", None)

        for exception in reversed(chain):
            if hasattr(exception, "context") and isinstance(exception.context, dict):
                merged_context.update(exception.context)

        _ALLOWED_ATTRS = frozenset(
            {
                "reason",
                "status",
                "status_code",
                "url",
                "request",
                "response",
                "message",
                "code",
                "detail",
                "name",
            }
        )
        excluded_attrs = {"args", "with_traceback", "context"}
        for attr_name in dir(exc):
            if (
                not attr_name.startswith("_")
                and attr_name not in excluded_attrs
                and attr_name in _ALLOWED_ATTRS
            ):
                try:
                    attr_value = getattr(exc, attr_name)
                    if not callable(attr_value) and isinstance(
                        attr_value, str | int | float | bool | type(None)
                    ):
                        merged_context[attr_name] = attr_value
                except Exception as exc_inner:
                    logger.debug(
                        "Failed to extract attribute %r from %s: %s",
                        attr_name,
                        type(exc).__name__,
                        exc_inner,
                    )

        for key, value in (additional_context or {}).items():
            if value is not None and merged_context.get(key) is None:
                merged_context[key] = value

        return merged_context
