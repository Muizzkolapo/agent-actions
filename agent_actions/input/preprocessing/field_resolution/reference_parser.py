"""Unified parser for field references across different syntaxes."""

import re
from dataclasses import dataclass
from enum import Enum

from .exceptions import InvalidReferenceError


class ReferenceFormat(Enum):
    """Supported field reference formats."""

    SELECTOR = "selector"  # action.field (guards, context_scope)
    TEMPLATE = "template"  # {action.field} (legacy prompts)
    JINJA = "jinja"  # {{ action.field }} (modern prompts)


@dataclass
class ParsedReference:
    """Structured representation of a parsed field reference."""

    action_name: str
    field_path: list[str]
    full_reference: str
    format_type: "ReferenceFormat"

    @property
    def field_name(self) -> str:
        """Get the top-level field name (first element of path)."""
        return self.field_path[0] if self.field_path else ""

    @property
    def is_nested(self) -> bool:
        """Check if this is a nested path reference (more than one level)."""
        return len(self.field_path) > 1

    @property
    def full_path(self) -> str:
        """Get full dotted path including action name."""
        return f"{self.action_name}.{'.'.join(self.field_path)}"


class ReferenceParser:
    """Unified parser for all field reference formats."""

    # Regex patterns for extracting references from text
    # Template: {action.field} or {action.nested.path}
    TEMPLATE_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+)\}")

    # Jinja: {{ action.field }} with optional whitespace
    JINJA_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+)\s*\}\}")

    # Selector in expressions: action.field patterns (for guards)
    # Matches word.word patterns that aren't inside quotes
    SELECTOR_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+)\b")

    def parse(
        self, reference: str, format_hint: ReferenceFormat | None = None, strict: bool = False
    ) -> "ParsedReference | None":
        """Parse a single field reference string into structured format.

        Raises:
            InvalidReferenceError: If reference is malformed (strict mode only).
        """
        if not reference or not isinstance(reference, str):
            if strict:
                raise InvalidReferenceError(
                    f"Invalid reference: {reference!r}. Expected non-empty string."
                )
            return None

        reference = reference.strip()

        if format_hint:
            result = self._try_parse_format(reference, format_hint, strict)
            if result:
                return result

        for fmt in [ReferenceFormat.JINJA, ReferenceFormat.TEMPLATE, ReferenceFormat.SELECTOR]:
            result = self._try_parse_format(reference, fmt, strict=False)
            if result:
                return result

        if strict:
            raise InvalidReferenceError(
                f"Invalid reference: '{reference}'. "
                f"Expected format: 'action.field' or '{{action.field}}'"
            )

        try:
            return self._parse_selector_format(reference, ReferenceFormat.SELECTOR)
        except InvalidReferenceError:
            return None

    def parse_batch(
        self, text: str, format_hint: ReferenceFormat | None = None, strict: bool = False
    ) -> list[ParsedReference]:
        """Extract all field references from a text string."""
        if not text:
            return []

        references = []
        seen = set()

        patterns = self._get_patterns_for_format(format_hint)

        for pattern, fmt in patterns:
            for match in pattern.finditer(text):
                full_match = match.group(0)
                ref_content = match.group(1)

                if ref_content in seen:
                    continue
                seen.add(ref_content)

                try:
                    parsed = self._parse_selector_format(ref_content, fmt)
                    # Override full_reference with actual match from text
                    parsed = ParsedReference(
                        action_name=parsed.action_name,
                        field_path=parsed.field_path,
                        full_reference=full_match,
                        format_type=fmt,
                    )
                    references.append(parsed)
                except InvalidReferenceError:
                    if strict:
                        raise
                    continue

        return references

    def _try_parse_format(
        self, reference: str, fmt: ReferenceFormat, strict: bool
    ) -> ParsedReference | None:
        """Try parsing reference with specific format."""
        try:
            if fmt == ReferenceFormat.SELECTOR:
                return self._parse_selector_format(reference, fmt)
            if fmt == ReferenceFormat.TEMPLATE:
                return self._parse_template_format(reference, fmt)
            if fmt == ReferenceFormat.JINJA:
                return self._parse_jinja_format(reference, fmt)
        except (InvalidReferenceError, ValueError):
            if strict:
                raise
            return None
        return None  # type: ignore[unreachable]

    def _parse_selector_format(self, reference: str, fmt: ReferenceFormat) -> ParsedReference:
        """Parse selector format: action.field or action.nested.path."""
        parts = reference.split(".")

        if len(parts) < 2:
            raise InvalidReferenceError(
                f"Invalid selector: '{reference}'. "
                f"Expected format: 'action.field' (at least one dot required)"
            )

        action_name = parts[0]
        field_path = parts[1:]

        if not action_name:
            raise InvalidReferenceError(
                f"Invalid selector: '{reference}'. Action name cannot be empty."
            )

        if not all(field_path):
            raise InvalidReferenceError(
                f"Invalid selector: '{reference}'. Field path components cannot be empty."
            )

        return ParsedReference(
            action_name=action_name,
            field_path=field_path,
            full_reference=reference,
            format_type=fmt,
        )

    def _parse_template_format(self, reference: str, fmt: ReferenceFormat) -> ParsedReference:
        """Parse template format: {action.field}"""
        if not (reference.startswith("{") and reference.endswith("}")):
            raise InvalidReferenceError(
                f"Invalid template reference: '{reference}'. Expected format: '{{action.field}}'"
            )

        content = reference[1:-1].strip()
        parsed = self._parse_selector_format(content, fmt)

        return ParsedReference(
            action_name=parsed.action_name,
            field_path=parsed.field_path,
            full_reference=reference,
            format_type=fmt,
        )

    def _parse_jinja_format(self, reference: str, fmt: ReferenceFormat) -> ParsedReference:
        """Parse Jinja format: {{ action.field }}"""
        if not (reference.startswith("{{") and reference.endswith("}}")):
            raise InvalidReferenceError(
                f"Invalid Jinja reference: '{reference}'. Expected format: '{{{{ action.field }}}}'"
            )

        content = reference[2:-2].strip()
        parsed = self._parse_selector_format(content, fmt)

        return ParsedReference(
            action_name=parsed.action_name,
            field_path=parsed.field_path,
            full_reference=reference,
            format_type=fmt,
        )

    def _get_patterns_for_format(self, format_hint: ReferenceFormat | None) -> list[tuple]:
        """Get regex patterns to use based on format hint."""
        if format_hint == ReferenceFormat.TEMPLATE:
            return [(self.TEMPLATE_PATTERN, ReferenceFormat.TEMPLATE)]
        if format_hint == ReferenceFormat.JINJA:
            return [(self.JINJA_PATTERN, ReferenceFormat.JINJA)]
        if format_hint == ReferenceFormat.SELECTOR:
            return [(self.SELECTOR_PATTERN, ReferenceFormat.SELECTOR)]
        return [
            (self.JINJA_PATTERN, ReferenceFormat.JINJA),
            (self.TEMPLATE_PATTERN, ReferenceFormat.TEMPLATE),
            (self.SELECTOR_PATTERN, ReferenceFormat.SELECTOR),
        ]
