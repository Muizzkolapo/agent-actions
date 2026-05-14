"""Pre-process Jinja2 templates to escape syntax inside markdown inline code.

Prompt templates frequently contain literal Jinja-like syntax as code examples
(e.g., dbt's ``{% test %}``, Django's ``{% block %}``).  Jinja2 parses the
entire template upfront and chokes on unknown tags, even when they appear
inside markdown backtick spans that are clearly literal text.

This module provides a single pre-processing function that wraps ``{% %}``
and ``{{ }}`` tokens found inside markdown inline code spans with
``{% raw %}...{% endraw %}``, so Jinja2 skips them.  The ``{% raw %}`` /
``{% endraw %}`` directives are stripped during rendering, producing the
original literal text in the output.

Fenced code blocks (````` ``` `````) are **not** escaped because they can
legitimately contain real Jinja2 expressions (e.g.,
``{{ generate_optimal_code.optimal_code }}``).
"""

from __future__ import annotations

import re

# Matches markdown inline code spans: `...` or ``...``
# - Captures the opening backtick(s) as group 1
# - (?!`) prevents matching the opening of a fenced code block (```)
# - Captures content as group 2
# - Uses a backreference (\1) to match the closing backtick(s)
_INLINE_CODE_RE = re.compile(
    r"(`{1,2})"  # group 1: opening backtick(s)
    r"(?!`)"  # not followed by another backtick (excludes ```)
    r"([^\n]*?)"  # group 2: content (non-greedy, single line only)
    r"(?<!`)"  # content doesn't end with a backtick
    r"\1",  # closing backtick(s) must match opening
)

_JINJA_BLOCK_OR_VAR = re.compile(r"\{[%{]")


def escape_jinja_in_inline_code(template: str) -> str:
    """Wrap Jinja2 syntax inside markdown inline code with ``{% raw %}``.

    Only affects content within backtick-delimited inline code spans
    (single or double backticks).  Real Jinja2 outside backticks and
    content inside fenced code blocks (triple backticks) is untouched.

    Parameters
    ----------
    template:
        Raw template string, potentially containing markdown with inline
        code spans that include Jinja-like syntax.

    Returns
    -------
    str
        Template with Jinja syntax inside inline code spans escaped.

    Examples
    --------
    >>> escape_jinja_in_inline_code("Use `{% test %}` in your code")
    'Use `{% raw %}{% test %}{% endraw %}` in your code'

    >>> escape_jinja_in_inline_code("{% for x in items %}{{ x }}{% endfor %}")
    '{% for x in items %}{{ x }}{% endfor %}'
    """
    if "{" not in template:
        return template

    def _escape_match(match: re.Match[str]) -> str:
        backticks: str = match.group(1)
        content: str = match.group(2)
        if _JINJA_BLOCK_OR_VAR.search(content):
            return f"{backticks}{{% raw %}}{content}{{% endraw %}}{backticks}"
        return str(match.group(0))

    result: str = _INLINE_CODE_RE.sub(_escape_match, template)
    return result
