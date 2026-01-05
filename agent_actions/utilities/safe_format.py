"""
Safe error formatting utilities that never crash.

This module provides bulletproof error formatting functions that handle
all edge cases including broken __str__ methods, circular references,
and malformed exception chains.
"""

import logging
from typing import Any, Set

logger = logging.getLogger(__name__)


def safe_format_error(exc: Any) -> str:
    """Safely format any exception without risk of cascading failures."""
    if exc is None:
        return "None"

    # Try str() first
    try:
        result = str(exc)
        if result:  # Make sure it's not empty
            return result
    except Exception:
        pass  # Continue to next approach

    # Try repr() as fallback
    try:
        result = repr(exc)
        if result:
            return result
    except Exception:
        pass  # Continue to next approach

    # Try to get the class name
    try:
        class_name = type(exc).__name__
        return f"<{class_name}: unable to format message>"
    except Exception:
        pass  # Continue to ultimate fallback

    # Ultimate fallback - this should never fail
    return "<Exception: formatting completely failed>"


def extract_root_cause(exc: Exception, max_depth: int = 10) -> Exception:
    """Walk exception chain to find root cause, handling circular references safely."""
    if not isinstance(exc, Exception):
        return exc

    visited: Set[id] = set()  # Track visited exceptions to detect cycles
    current = exc
    depth = 0

    while depth < max_depth:
        # Prevent infinite loops from circular references
        exc_id = id(current)
        if exc_id in visited:
            logger.debug("Circular reference detected in exception chain at depth %s", depth)
            break
        visited.add(exc_id)

        # Look for the next exception in the chain
        next_exc = None

        # Try __cause__ first (explicit chaining with 'from')
        try:
            if hasattr(current, "__cause__") and current.__cause__ is not None:
                next_exc = current.__cause__
        except Exception:
            logger.debug("Error accessing __cause__")

        # Try __context__ if no __cause__ (implicit chaining)
        if next_exc is None:
            try:
                if hasattr(current, "__context__") and current.__context__ is not None:
                    next_exc = current.__context__
            except Exception:
                logger.debug("Error accessing __context__")

        # If no next exception, we've reached the end
        if next_exc is None:
            break

        current = next_exc
        depth += 1

    return current


def get_error_chain(exc: Exception, max_depth: int = 10) -> list:
    """Get the full exception chain as a list, from outermost to root cause."""
    if not isinstance(exc, Exception):
        return [exc]

    chain = []
    visited: Set[id] = set()
    current = exc
    depth = 0

    while depth < max_depth and current is not None:
        # Prevent cycles
        exc_id = id(current)
        if exc_id in visited:
            break
        visited.add(exc_id)

        chain.append(current)

        # Get next exception in chain
        next_exc = None
        try:
            if hasattr(current, "__cause__") and current.__cause__ is not None:
                next_exc = current.__cause__
            elif hasattr(current, "__context__") and current.__context__ is not None:
                next_exc = current.__context__
        except Exception:
            break

        current = next_exc
        depth += 1

    return chain


def safe_get_exception_message(exc: Exception) -> str:
    """Safely extract just the message portion of an exception."""
    if not isinstance(exc, Exception):
        return safe_format_error(exc)

    # Try to get the args[0] which is usually the message
    try:
        if hasattr(exc, "args") and exc.args:
            first_arg = exc.args[0]
            if isinstance(first_arg, str) and first_arg.strip():
                return first_arg.strip()
    except Exception:
        pass

    # Fallback to safe_format_error
    return safe_format_error(exc)


def format_exception_context(context: Any, max_list_items: int = 10) -> str:
    """Safely format exception context (usually a dict).

    Args:
        context: The context to format (usually a dict)
        max_list_items: Maximum items to show for lists (default 10)
    """
    if context is None:
        return ""

    if isinstance(context, dict):
        try:
            if not context:  # Empty dict
                return ""
            items = []
            for key, value in context.items():
                # Safely format each key-value pair
                safe_key = safe_format_error(key)
                # Truncate long lists for readability
                if isinstance(value, (list, tuple)) and len(value) > max_list_items:
                    shown = list(value[:max_list_items])
                    remaining = len(value) - max_list_items
                    safe_value = f"{shown} (+{remaining} more)"
                else:
                    safe_value = safe_format_error(value)
                items.append(f"{safe_key}={safe_value}")
            return ", ".join(items)
        except Exception:
            return safe_format_error(context)

    return safe_format_error(context)


def format_exception_chain_for_debug(exc: Exception, max_depth: int = 10) -> str:
    """Format the complete exception chain for debugging purposes."""
    try:
        chain = get_error_chain(exc, max_depth)

        if not chain:
            return safe_format_error(exc)

        lines = [f"Exception Chain ({len(chain)} level{'s' if len(chain) != 1 else ''}):"]
        lines.append("")

        for idx, current_exc in enumerate(chain, 1):
            # Exception type and message
            exc_type = type(current_exc).__name__
            exc_msg = safe_get_exception_message(current_exc)
            lines.append(f"[{idx}] {exc_type}: {exc_msg}")

            # Add context if available
            if hasattr(current_exc, "context") and current_exc.context:
                context_str = format_exception_context(current_exc.context)
                if context_str:
                    lines.append(f"    Context: {context_str}")

            # Mark root cause
            if idx == len(chain):
                lines.append("    (Root Cause)")

            lines.append("")

        return "\n".join(lines)

    except Exception as format_error:
        logger.error("Failed to format exception chain: %s", format_error)
        return f"Exception chain formatting failed. Original error: {safe_format_error(exc)}"
