"""Function/UDF error formatter."""

from difflib import SequenceMatcher
from typing import Dict, Any, List
from .base import ErrorFormatter
from ..user_error import UserError


class FunctionNotFoundFormatter(ErrorFormatter):
    """Handles function/UDF not found errors with helpful suggestions."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        """Detect function not found errors."""
        exc_names = [type(exc).__name__, type(root).__name__]
        if "FunctionNotFoundError" in exc_names:
            return True

        if "function" in message.lower() and "not found" in message.lower():
            return True

        return False

    def format(
        self, exc: Exception, root: Exception, message: str, context: Dict[str, Any]
    ) -> UserError:
        """Format function not found errors with suggestions."""
        function_name = context.get("function_name", "unknown")
        available_functions = context.get("available_functions", [])

        # Build title
        title = f"Function '{function_name}' not found"

        # Build details
        details = (
            f"The function '{function_name}' is not registered as a UDF (User Defined Function)."
        )

        # Find similar function names
        similar = self._find_similar_functions(function_name, available_functions)

        # Build fix message
        fix_parts = []
        if similar:
            fix_parts.append("Did you mean one of these?")
            for func in similar[:3]:  # Show top 3 matches
                fix_parts.append(f"  - {func}")
        else:
            fix_parts.append("Make sure the function is:")
            fix_parts.append("  1. Defined with the @udf_tool decorator")
            fix_parts.append("  2. Located in the user_code directory")
            fix_parts.append("  3. Spelled correctly in your config")

        if available_functions:
            count = len(available_functions)
            fix_parts.append(f"\nRun 'agac list-udfs' to see all {count} available functions.")

        return UserError(
            category="Configuration Error",
            title=title,
            details=details,
            fix="\n".join(fix_parts),
            context={
                "function_name": function_name,
                "similar_functions": similar[:3] if similar else None,
            },
            docs_url="https://docs.agent-actions.com/user-defined-functions",
        )

    def _find_similar_functions(self, target: str, available: List[str]) -> List[str]:
        """Find similar function names using simple string matching."""
        if not available:
            return []

        target_lower = target.lower()
        matches = []

        # Exact case-insensitive match
        for func in available:
            if func.lower() == target_lower:
                return [func]

        # Partial matches (target contains func or func contains target)
        for func in available:
            func_lower = func.lower()
            if target_lower in func_lower or func_lower in target_lower:
                matches.append((func, self._similarity_score(target_lower, func_lower)))

        # Sort by similarity score (higher is better)
        matches.sort(key=lambda x: x[1], reverse=True)

        return [func for func, _ in matches]

    def _similarity_score(self, s1: str, s2: str) -> int:
        """Calculate similarity score using longest common substring (O(n²) via difflib)."""
        # Use SequenceMatcher which is much more efficient than O(n³) brute force
        match = SequenceMatcher(None, s1, s2).find_longest_match(0, len(s1), 0, len(s2))
        return match.size
