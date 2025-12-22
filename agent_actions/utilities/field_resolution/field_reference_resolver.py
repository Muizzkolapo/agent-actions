"""
Centralized service for parsing and resolving field references.

This is the main entry point for field reference operations across the codebase.
Provides unified parsing, resolution, and substitution for field references in
guards, prompts, filters, and context_scope directives.

Features:
- Multiple syntax support: selector (action.field), template ({action.field}), Jinja
- Nested path resolution: action.response.data.status
- Array index support: action.items.0.name
- Validation against dependency graph
- Substitution in text strings

Example:
    resolver = FieldReferenceResolver()

    # Parse and resolve a reference
    result = resolver.resolve(
        "extract_facts.response.count",
        field_context={'extract_facts': {'response': {'count': 5}}}
    )
    # result.value = 5

    # Substitute in text
    text = resolver.substitute(
        "Found {source.title} with {extract.count} items",
        field_context
    )
    # "Found My Document with 5 items"
"""
# pylint: disable=line-too-long
# Line-too-long: Complex method signatures require longer lines

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from .reference_parser import ParsedReference, ReferenceFormat, ReferenceParser
from .exceptions import ReferenceNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class ResolvedReference:
    """
    Result of resolving a field reference.

    Attributes:
        value: The resolved value (can be any type)
        source_action: Name of the action that provided the value
        field_path: Path to the value within the action's data
        success: Whether resolution succeeded
        error: Error message if resolution failed
    """

    value: Any
    source_action: str
    field_path: List[str]
    success: bool = True
    error: Optional[str] = None


class FieldReferenceResolver:
    """
    Centralized service for parsing and resolving field references.

    Provides a unified API for field reference operations across guards,
    prompts, filters, and context_scope directives.

    Attributes:
        strict_mode: If True, raise errors on invalid/unresolvable references
        validate_dependencies: If True, validate references against dependency graph

    Example:
        # Basic usage
        resolver = FieldReferenceResolver()

        # Parse a reference
        ref = resolver.parse("extract_facts.count")

        # Resolve to value
        result = resolver.resolve(ref, field_context)
        if result.success:
            print(f"Value: {result.value}")

        # Substitute in text
        text = resolver.substitute(
            "Found {extract.count} items",
            field_context
        )
    """

    def __init__(
        self,
        strict_mode: bool = False,
        validate_dependencies: bool = True
    ):
        """
        Initialize the resolver.

        Args:
            strict_mode: If True, raise errors on invalid references
            validate_dependencies: If True, validate against dependency graph
        """
        self.strict_mode = strict_mode
        self.validate_dependencies = validate_dependencies
        self._parser = ReferenceParser()

    def parse(
        self,
        reference: str,
        format_hint: Optional[ReferenceFormat] = None
    ) -> ParsedReference:
        """
        Parse a field reference string into structured format.

        Args:
            reference: Reference string (e.g., "action.field" or "{action.field}")
            format_hint: Optional hint about expected format

        Returns:
            ParsedReference with action name and field path

        Raises:
            InvalidReferenceError: If reference is malformed (strict mode)

        Example:
            >>> resolver = FieldReferenceResolver()
            >>> ref = resolver.parse("extract_facts.response.data.count")
            >>> ref.action_name
            'extract_facts'
            >>> ref.field_path
            ['response', 'data', 'count']
        """
        return self._parser.parse(reference, format_hint, self.strict_mode)

    def parse_batch(
        self,
        text: str,
        format_hint: Optional[ReferenceFormat] = None
    ) -> List[ParsedReference]:
        """
        Extract all field references from a text string.

        Args:
            text: Text containing references
            format_hint: Expected reference format

        Returns:
            List of ParsedReference objects found in text

        Example:
            >>> resolver = FieldReferenceResolver()
            >>> refs = resolver.parse_batch(
            ...     "extract.count > 5 AND source.type == 'doc'"
            ... )
            >>> len(refs)
            2
        """
        return self._parser.parse_batch(text, format_hint, self.strict_mode)

    def resolve(
        self,
        reference: Union[str, ParsedReference],
        field_context: Dict[str, Any],
        fallback_value: Any = None
    ) -> ResolvedReference:
        """
        Resolve a field reference to its value in the context.

        Supports nested paths and array indices for deep field access.

        Args:
            reference: Reference string or ParsedReference
            field_context: Nested context dict {action_name: {field: value}}
            fallback_value: Value to return if resolution fails

        Returns:
            ResolvedReference with value and metadata

        Example:
            field_context = {
                'extract_facts': {
                    'response': {
                        'data': {'count': 5}
                    }
                }
            }

            result = resolver.resolve(
                'extract_facts.response.data.count',
                field_context
            )
            # result.value = 5
        """
        # Parse if string
        if isinstance(reference, str):
            try:
                reference = self.parse(reference)
            except Exception as e:
                return ResolvedReference(
                    value=fallback_value,
                    source_action="",
                    field_path=[],
                    success=False,
                    error=str(e)
                )

        try:
            # Check if action exists in context
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
                    error=error_msg
                )

            action_data = field_context[reference.action_name]

            # Navigate nested path
            value = self._resolve_nested_path(action_data, reference.field_path)

            if value is None and self.strict_mode:
                raise ReferenceNotFoundError(
                    f"Field path '{'.'.join(reference.field_path)}' not found "
                    f"in action '{reference.action_name}'"
                )

            return ResolvedReference(
                value=value if value is not None else fallback_value,
                source_action=reference.action_name,
                field_path=reference.field_path,
                success=value is not None
            )

        except ReferenceNotFoundError:
            raise
        except Exception as e:
            if self.strict_mode:
                raise

            return ResolvedReference(
                value=fallback_value,
                source_action=reference.action_name,
                field_path=reference.field_path,
                success=False,
                error=str(e)
            )

    def resolve_batch(
        self,
        references: List[Union[str, ParsedReference]],
        field_context: Dict[str, Any]
    ) -> Dict[str, ResolvedReference]:
        """
        Resolve multiple references efficiently.

        Args:
            references: List of reference strings or ParsedReference objects
            field_context: Context to resolve from

        Returns:
            Dict mapping reference string to ResolvedReference
        """
        results = {}

        for ref in references:
            ref_str = ref if isinstance(ref, str) else ref.full_reference
            results[ref_str] = self.resolve(ref, field_context)

        return results

    def substitute(
        self,
        text: str,
        field_context: Dict[str, Any],
        format_hint: Optional[ReferenceFormat] = None
    ) -> str:
        """
        Replace all field references in text with their resolved values.

        Args:
            text: Text containing field references
            field_context: Context to resolve from
            format_hint: Expected reference format (auto-detects if not provided)

        Returns:
            Text with references replaced by values

        Example:
            text = "Found {extract.count} items in {source.title}"
            result = resolver.substitute(text, field_context)
            # "Found 5 items in My Document"
        """
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
                    "Could not resolve reference '%s': %s",
                    ref.full_reference,
                    resolved.error
                )

        return text

    def validate_references(
        self,
        references: List[Union[str, ParsedReference]],
        agent_config: Dict[str, Any],
        agent_indices: Dict[str, int],
        current_agent_name: Optional[str] = None
    ) -> List[str]:
        """
        Validate that referenced actions exist in dependency graph.

        Args:
            references: References to validate
            agent_config: Current agent configuration
            agent_indices: Mapping of agent names to their indices
            current_agent_name: Name of current agent (for index lookup)

        Returns:
            List of error messages (empty if all valid)
        """
        # Import here to avoid circular dependency
        from .reference_validator import ReferenceValidator

        validator = ReferenceValidator()
        return validator.validate(
            references=references,
            agent_config=agent_config,
            agent_indices=agent_indices,
            current_agent_name=current_agent_name
        )

    def _resolve_nested_path(self, data: Any, path: List[str]) -> Any:
        """
        Resolve a nested path like ['response', 'data', 'count'].

        Supports both dict key access and array index access.
        """
        current = data

        for key in path:
            if current is None:
                return None

            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list) and key.isdigit():
                idx = int(key)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                # Try attribute access as last resort
                if hasattr(current, key):
                    current = getattr(current, key)
                else:
                    return None

        return current

    def _format_value(self, value: Any) -> str:
        """Format a resolved value for string substitution."""
        if value is None:
            return ""
        elif isinstance(value, (dict, list)):
            return json.dumps(value, indent=2, ensure_ascii=False)
        elif isinstance(value, bool):
            return str(value).lower()
        else:
            return str(value)
