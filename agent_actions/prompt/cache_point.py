"""The `{% cache_point %}` tag of a prompt template.

The tag renders to no text. It says the text before it is shared by many records, so a
vendor that caches a marked prefix can be told where that prefix ends. Every Jinja
environment that reads a prompt takes `PROMPT_EXTENSIONS`, or the tag is a syntax error.
"""

from __future__ import annotations

import re
import secrets
from typing import Any

from jinja2 import nodes
from jinja2.ext import Extension

CACHE_POINT_TAG = "cache_point"

CACHE_POINT_TAG_PATTERN = re.compile(r"\{%[-+]?\s*" + CACHE_POINT_TAG + r"\s*[-+]?%\}")
"""The tag as a template writes it, whitespace control included."""

# A tag at the end of a line of text, before its newline: `trim_blocks` would eat the
# newline, so the line would join the next one. A tag alone on its line is left to it.
_INLINE_TAG_AT_LINE_END = re.compile(
    r"(?m)^(?P<before>[^\n]*\S[^\n]*?)(?P<tag>\{%\+?\s*" + CACHE_POINT_TAG + r"\s*%\})\n"
)

# A tag alone on its line, with that line's newline: the line the render removes.
_TAG_LINE = re.compile(r"(?m)^[ \t]*\{%[-+]?\s*" + CACHE_POINT_TAG + r"\s*[-+]?%\}[ \t]*(?:\n|$)")

# `{% raw %}` text stays as written, a tag in it included.
_RAW_BLOCK = re.compile(r"(\{%-?\s*raw\s*-?%\}.*?\{%-?\s*endraw\s*-?%\})", re.S)

MAX_CACHE_POINTS = 3
"""The most tags a template may hold. Anthropic takes four cache breakpoints in a request;
one is kept for the end of a prompt that every record shares."""

# Stands where a tag rendered: private-use characters around a token drawn for this
# process, digits so no case filter changes it, so no record text can hold it.
_MARK = "\ue006" + str(secrets.randbits(128)).zfill(39) + "\ue007"


def has_cache_point(template: str) -> bool:
    """Whether *template* holds a `{% cache_point %}` tag."""
    return CACHE_POINT_TAG_PATTERN.search(template) is not None


def without_cache_points(template: str) -> str:
    """*template* as it is written without its tags: a tag's own line goes with it."""
    return CACHE_POINT_TAG_PATTERN.sub("", _TAG_LINE.sub("", template))


class CachePointExtension(Extension):
    """Renders `{% cache_point %}` to a mark that `take_cache_points` removes."""

    tags = {CACHE_POINT_TAG}
    output = _MARK

    def preprocess(self, source: str, name: str | None, filename: str | None = None) -> str:
        """Keep the newline after a tag inside a line, which `trim_blocks` would eat."""
        if not self.environment.trim_blocks:
            return source
        parts = _RAW_BLOCK.split(source)
        # The odd parts are `{% raw %}` blocks.
        return "".join(
            part if i % 2 else _INLINE_TAG_AT_LINE_END.sub(lambda m: m.group(0) + "\n", part)
            for i, part in enumerate(parts)
        )

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
