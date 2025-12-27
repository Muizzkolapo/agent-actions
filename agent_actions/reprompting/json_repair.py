"""JSON repair strategies for fixing common LLM JSON output errors.

This module provides repair strategies that can fix JSON errors without
making additional API calls. Repairs are attempted in order of likelihood.

Common issues fixed:
- Markdown code blocks (```json ... ```)
- Trailing commas in arrays/objects
- Single quotes instead of double quotes
- Unclosed brackets/braces
- Truncated JSON
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class RepairResult:
    """Result of JSON repair attempt.

    Attributes:
        success: Whether repair succeeded
        data: Parsed JSON data (if success)
        repair_method: Name of repair method that worked
        error: Error message (if failed)
    """

    success: bool
    data: Optional[Any] = None
    repair_method: Optional[str] = None
    error: Optional[str] = None


class JSONRepairStrategy:
    """Multi-stage JSON repair before reprompting.

    Attempts repairs in order of likelihood:
    1. Direct parse (maybe it's valid)
    2. Strip markdown code blocks
    3. Extract JSON from surrounding text
    4. Fix trailing commas
    5. Fix single quotes to double quotes
    6. Close unclosed brackets

    Usage:
        repair = JSONRepairStrategy()
        result = repair.attempt_repair(raw_text)
        if result.success:
            print(f"Fixed using {result.repair_method}")
            data = result.data
        else:
            print(f"Could not repair: {result.error}")
    """

    def attempt_repair(self, raw: str) -> RepairResult:  # pylint: disable=too-many-return-statements
        """Try all repair strategies in order.

        Args:
            raw: Raw text that should contain JSON

        Returns:
            RepairResult with success=True and data if any repair worked,
            or success=False with error if all repairs failed
        """
        if not raw or not raw.strip():
            return RepairResult(
                success=False,
                error="Empty or whitespace-only input",
            )

        # Strategy 1: Direct parse
        result = self._try_parse(raw)
        if result.success:
            return result

        # Strategy 2: Strip markdown
        stripped = self._strip_markdown(raw)
        if stripped != raw:
            result = self._try_parse(stripped)
            if result.success:
                result.repair_method = "strip_markdown"
                return result

        # Strategy 3: Extract JSON block
        extracted = self._extract_json_block(raw)
        if extracted:
            result = self._try_parse(extracted)
            if result.success:
                result.repair_method = "extract_json_block"
                return result

        # Strategy 4: Fix trailing commas
        fixed_commas = self._fix_trailing_commas(stripped or raw)
        result = self._try_parse(fixed_commas)
        if result.success:
            result.repair_method = "fix_trailing_commas"
            return result

        # Strategy 5: Fix quotes
        fixed_quotes = self._fix_quotes(fixed_commas)
        result = self._try_parse(fixed_quotes)
        if result.success:
            result.repair_method = "fix_quotes"
            return result

        # Strategy 6: Close brackets
        closed = self._close_brackets(fixed_quotes)
        result = self._try_parse(closed)
        if result.success:
            result.repair_method = "close_brackets"
            return result

        # All repairs failed
        return RepairResult(
            success=False,
            error=f"All repair strategies failed. Original parse error: {result.error}",
        )

    def _try_parse(self, text: str) -> RepairResult:
        """Try to parse text as JSON."""
        try:
            data = json.loads(text)
            return RepairResult(success=True, data=data, repair_method="direct_parse")
        except json.JSONDecodeError as e:
            return RepairResult(success=False, error=str(e))

    def _strip_markdown(self, text: str) -> str:
        """Remove markdown code blocks (```json ... ```)."""
        # Pattern for ```json or ``` blocks
        patterns = [
            r"```json\s*\n?(.*?)\n?```",  # ```json content ```
            r"```\s*\n?(.*?)\n?```",  # ``` content ```
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return text

    def _extract_json_block(self, text: str) -> Optional[str]:  # pylint: disable=too-many-branches
        """Extract JSON object or array from surrounding text.

        Finds the first { or [ and matches to its closing bracket.
        """
        # Find start of JSON
        obj_start = text.find("{")
        arr_start = text.find("[")

        if obj_start == -1 and arr_start == -1:
            return None

        # Use whichever comes first
        if obj_start == -1:
            start = arr_start
            open_char, close_char = "[", "]"
        elif arr_start == -1:
            start = obj_start
            open_char, close_char = "{", "}"
        elif obj_start < arr_start:
            start = obj_start
            open_char, close_char = "{", "}"
        else:
            start = arr_start
            open_char, close_char = "[", "]"

        # Find matching closing bracket
        depth = 0
        in_string = False
        escape_next = False

        for i, char in enumerate(text[start:], start):
            if escape_next:
                escape_next = False
                continue

            if char == "\\":
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

        # No matching close found - return from start to end
        return text[start:]

    def _fix_trailing_commas(self, text: str) -> str:
        """Remove trailing commas before } or ]."""
        # Remove trailing commas before closing brackets
        # Handle: ,] ,} , ] , }
        fixed = re.sub(r",\s*([\]}])", r"\1", text)
        return fixed

    def _fix_quotes(self, text: str) -> str:
        """Convert single quotes to double quotes for JSON strings.

        This is tricky because we need to avoid breaking valid content
        like contractions ("it's") inside strings.
        """
        # Simple approach: only fix quotes that look like JSON keys/values
        # Pattern: 'key': 'value' -> "key": "value"

        # Fix keys (word followed by colon)
        fixed = re.sub(r"'(\w+)'(\s*:)", r'"\1"\2', text)

        # Fix string values after colons
        # This is simplified - may not handle all cases
        fixed = re.sub(r":\s*'([^']*)'(\s*[,}\]])", r': "\1"\2', fixed)

        return fixed

    def _close_brackets(self, text: str) -> str:
        """Close any unclosed brackets/braces.

        Useful for truncated responses.
        """
        # Count open/close brackets
        open_braces = text.count("{") - text.count("}")
        open_brackets = text.count("[") - text.count("]")

        # Add missing closing brackets
        result = text.rstrip()

        # Remove trailing comma if present
        if result.endswith(","):
            result = result[:-1]

        # Add closing brackets in reverse order of opening
        # This is a simplification - won't work for all cases
        result += "]" * open_brackets
        result += "}" * open_braces

        return result

    def repair_and_parse(self, text: str) -> Tuple[Optional[Dict], Optional[str]]:
        """Convenience method: repair and return (data, repair_method) or (None, error).

        Args:
            text: Raw text to repair

        Returns:
            Tuple of (parsed_data, repair_method) if successful,
            or (None, error_message) if failed
        """
        result = self.attempt_repair(text)
        if result.success:
            return result.data, result.repair_method
        return None, result.error
