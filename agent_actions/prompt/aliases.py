"""The alias header that lets a prompt of an ``as:`` include read a name by its short form.

The load puts ``{% set write = c2__write %}`` before the prompt, one tag for each short name
the prompt reads, so one prompt text serves every instance. A static reader of prompt
references follows such a tag with ``prompt_aliases``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from jinja2 import Environment, TemplateSyntaxError, meta, nodes

from agent_actions.utils.template_escape import escape_jinja_in_inline_code

_ENV = Environment()


def with_alias_header(prompt: str, names: Mapping[str, str]) -> str:
    """*prompt* with a ``{% set short = final %}`` tag before it for each name it reads.

    The tags are on the prompt's first line and output nothing, so the prompt renders and
    numbers its lines as before. A prompt that reads no renamed name, or does not parse,
    is returned unchanged.
    """
    try:
        read = meta.find_undeclared_variables(_ENV.parse(escape_jinja_in_inline_code(prompt)))
    except TemplateSyntaxError:
        return prompt
    header = "".join(
        f"{{% set {short} = {final} %}}"
        for short, final in names.items()
        if short in read and final != short
    )
    if not header:
        return prompt
    # A block tag eats the newline after it under trim_blocks, as the per-record render
    # sets it; an empty output tag keeps a prompt's own first newline.
    return header + ('{{ "" }}' if prompt.startswith(("\n", "\r")) else "") + prompt


def header_names(action: Any) -> dict[str, str]:
    """The names the alias header of *action* may bind: the map of its ``as:`` include."""
    origin = action.get("_include") if isinstance(action, Mapping) else None
    names = origin.get("names") if isinstance(origin, Mapping) else None
    return dict(names) if isinstance(names, Mapping) else {}


def prompt_aliases(ast: nodes.Template, names: Mapping[str, str]) -> dict[str, str]:
    """Each name a top-level ``{% set a = b %}`` of the alias header binds, mapped to ``b``.

    Only a tag that *names* (the action's ``as:`` map) agrees with is followed, so a
    ``{% set %}`` the prompt writes itself is read as before. A name set more than once at
    the top level is left out, as it means different things.
    """
    aliases: dict[str, str] = {}
    assigned: Counter[str] = Counter()
    for node in ast.body:
        if not isinstance(node, nodes.Assign | nodes.AssignBlock):
            continue
        target = node.target
        targets = [target] if isinstance(target, nodes.Name) else target.find_all(nodes.Name)
        assigned.update(name.name for name in targets)
        if isinstance(node, nodes.Assign) and isinstance(target, nodes.Name):
            if isinstance(node.node, nodes.Name):
                aliases[target.name] = node.node.name
    return {
        name: value
        for name, value in aliases.items()
        if assigned[name] == 1 and names.get(name) == value
    }
