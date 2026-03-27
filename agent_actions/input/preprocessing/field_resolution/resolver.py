"""Centralized service for parsing and resolving field references."""

import json
import logging
from dataclasses import dataclass
from typing import Any

from .exceptions import ReferenceNotFoundError
from .reference_parser import ParsedReference, ReferenceFormat, ReferenceParser
from .validator import ReferenceValidator

logger = logging.getLogger(__name__)


@dataclass
class ResolvedReference:
    """Result of resolving a field reference."""

    value: Any
    source_action: str
    field_path: list[str]
    success: bool = True
    error: str | None = None


class FieldReferenceResolver:
    """Unified API for field reference parsing and resolution."""

    def __init__(self, strict_mode: bool = False, validate_dependencies: bool = True):
        """Initialize the resolver."""
        self.strict_mode = strict_mode
        self.validate_dependencies = validate_dependencies
        self._parser = ReferenceParser()

    def parse(
        self, reference: str, format_hint: ReferenceFormat | None = None
    ) -> "ParsedReference | None":
        """Parse a field reference string into structured format.

        Returns None if the reference is malformed and strict mode is off.
        Raises:
            InvalidReferenceError: If reference is malformed (strict mode only).
        """
        return self._parser.parse(reference, format_hint, self.strict_mode)

    def parse_batch(
        self, text: str, format_hint: ReferenceFormat | None = None
    ) -> list[ParsedReference]:
        """Extract all field references from a text string."""
        return self._parser.parse_batch(text, format_hint, self.strict_mode)

    def resolve(
        self,
        reference: str | ParsedReference,
        field_context: dict[str, Any],
        fallback_value: Any = None,
    ) -> ResolvedReference:
        """Resolve a field reference to its value in the context.

        Supports nested paths and array indices for deep field access.
        """
        if isinstance(reference, str):
            try:
                parsed = self.parse(reference)
            except (ValueError, TypeError, KeyError) as e:
                return ResolvedReference(
                    value=fallback_value,
                    source_action="",
                    field_path=[],
                    success=False,
                    error=str(e),
                )
            if parsed is None:
                return ResolvedReference(
                    value=fallback_value,
                    source_action="",
                    field_path=[],
                    success=False,
                    error=f"Failed to parse field reference: {reference!r}",
                )
            reference = parsed

        try:
            if reference.action_name not in field_context:
                error_msg = (
                    f"Action '{reference.action_name}' not found in context. "
                    f"Available: {list(field_context.keys())}"
                )

                if self.strict_mode:
                    raise ReferenceNotFoundError(error_msg)

                return ResolvedReference(
                    value=fallback_value,
                    source_action=reference.action_name,
                    field_path=reference.field_path,
                    success=False,
                    error=error_msg,
                )

            action_data = field_context[reference.action_name]

            value = self._resolve_nested_path(action_data, reference.field_path)

            if value is self._SENTINEL and self.strict_mode:
                raise ReferenceNotFoundError(
                    f"Field path '{'.'.join(reference.field_path)}' not found "
                    f"in action '{reference.action_name}'"
                )

            return ResolvedReference(
                value=value if value is not self._SENTINEL else fallback_value,
                source_action=reference.action_name,
                field_path=reference.field_path,
                success=value is not self._SENTINEL,
            )

        except ReferenceNotFoundError as e:
            if self.strict_mode:
                raise ReferenceNotFoundError(
                    f"{e}. Reference: {reference.action_name}.{'.'.join(reference.field_path)}"
                ) from e
            raise
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            if self.strict_mode:
                raise

            return ResolvedReference(
                value=fallback_value,
                source_action=reference.action_name,
                field_path=reference.field_path,
                success=False,
                error=str(e),
            )

    def resolve_batch(
        self, references: list[str | ParsedReference], field_context: dict[str, Any]
    ) -> dict[str, ResolvedReference]:
        """Resolve multiple references efficiently."""
        results = {}

        for ref in references:
            ref_str = ref if isinstance(ref, str) else ref.full_reference
            results[ref_str] = self.resolve(ref, field_context)

        return results

    def substitute(
        self,
        text: str,
        field_context: dict[str, Any],
        format_hint: ReferenceFormat | None = None,
    ) -> str:
        """Replace all field references in text with their resolved values."""
        if not text:
            return text

        references = self.parse_batch(text, format_hint)

        for ref in references:
            resolved = self.resolve(ref, field_context)

            if resolved.success:
                value_str = self._format_value(resolved.value)
                text = text.replace(ref.full_reference, value_str)
            else:
                logger.debug(
                    "Could not resolve reference '%s': %s", ref.full_reference, resolved.error
                )

        return text

    def validate_references(
        self,
        references: list[str | ParsedReference],
        agent_config: dict[str, Any],
        agent_indices: dict[str, int],
        current_agent_name: str | None = None,
    ) -> list[str]:
        """Validate that referenced actions exist in the dependency graph."""
        validator = ReferenceValidator()
        return validator.validate(
            references=references,
            agent_config=agent_config,
            agent_indices=agent_indices,
            current_agent_name=current_agent_name,
        )

    _SENTINEL = object()  # Distinguishes "key missing" from "key present with None value"

    def _resolve_nested_path(self, data: Any, path: list[str]) -> Any:
        """Resolve a nested path, supporting both dict key access and array index access.

        Returns _SENTINEL for missing keys, or the actual value (including None) for present keys.
        """
        current = data

        for key in path:
            if current is None:
                return self._SENTINEL

            if isinstance(current, dict):
                current = current.get(key, self._SENTINEL)
                if current is self._SENTINEL:
                    return self._SENTINEL
            elif isinstance(current, list) and key.isdigit():
                idx = int(key)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return self._SENTINEL
            else:
                if hasattr(current, key):
                    current = getattr(current, key)
                else:
                    return self._SENTINEL

        return current

    def _format_value(self, value: Any) -> str:
        """Format a resolved value for string substitution."""
        if value is None:
            return ""
        if isinstance(value, dict | list):
            return json.dumps(value, indent=2, ensure_ascii=False)
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)
