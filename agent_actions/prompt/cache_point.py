"""The `{% cache_point %}` tag of a prompt template.

The tag renders to no text. It says the text before it is shared by many records, so a
vendor that caches a marked prefix can be told where that prefix ends. Every Jinja
environment that reads a prompt takes `PROMPT_EXTENSIONS`, or the tag is a syntax error.
"""

from __future__ import annotations

from typing import Any

from jinja2 import nodes
from jinja2.ext import Extension

CACHE_POINT_TAG = "cache_point"

MAX_CACHE_POINTS = 3
"""The most tags a template may hold. Anthropic takes four cache breakpoints in a request;
one is kept for the end of a prompt that every record shares."""

# Private-use characters, which no prompt text holds and no case filter changes, stand
# where a tag rendered.
_MARK = "\ue006\ue007"


class CachePointExtension(Extension):
    """Renders `{% cache_point %}` to a mark that `take_cache_points` removes."""

    tags = {CACHE_POINT_TAG}
    output = _MARK

    def parse(self, parser: Any) -> nodes.Node:
        lineno = next(parser.stream).lineno
        return nodes.Output([nodes.TemplateData(self.output)], lineno=lineno)


class KeptCachePointExtension(CachePointExtension):
    """Renders the tag to itself, where the text is a template that renders again per record."""

    output = "{% " + CACHE_POINT_TAG + " %}"


PROMPT_EXTENSIONS = (CachePointExtension,)


def take_cache_points(rendered: str) -> tuple[str, tuple[int, ...]]:
    """*rendered* without its marks, and the length of the text before each."""
    if _MARK not in rendered:
        return rendered, ()
    parts = rendered.split(_MARK)
    points = []
    length = 0
    for part in parts[:-1]:
        length += len(part)
        points.append(length)
    return "".join(parts), tuple(points)


def is_cache_point(node: nodes.Node) -> bool:
    """Whether *node* is what a `{% cache_point %}` tag parsed to."""
    return (
        isinstance(node, nodes.Output)
        and len(node.nodes) == 1
        and isinstance(node.nodes[0], nodes.TemplateData)
        and node.nodes[0].data in (CachePointExtension.output, KeptCachePointExtension.output)
    )
