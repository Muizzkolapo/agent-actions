"""Optional dependency compatibility helpers."""

try:
    from rich.console import Console
    from rich.tree import Tree

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    # Placeholders when Rich is unavailable; type ignores needed for None assignment
    Console = None  # type: ignore[misc, assignment]
    Tree = None  # type: ignore[misc, assignment]

__all__ = ["RICH_AVAILABLE", "Console", "Tree"]
