"""Which observed fields a request sends in its context block, beside the rendered prompt.

Under ``context_block: auto`` a field the prompt template prints as it is, ``{{ ns.field }}``
at the top level of the template, is not sent a second time in the context block.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from jinja2 import Environment, TemplateSyntaxError, nodes

from agent_actions.output.response.config_fields import get_default
from agent_actions.prompt.cache_point import PROMPT_EXTENSIONS
from agent_actions.prompt.formatter import PromptFormatter
from agent_actions.prompt.message_builder import PROVIDER_MESSAGE_CONFIGS, MessageRole
from agent_actions.utils.constants import DEFAULT_ACTION_KIND
from agent_actions.utils.template_escape import escape_jinja_in_inline_code

logger = logging.getLogger(__name__)

CONTEXT_BLOCK_KEY = "context_block"


def context_block(context: Any, agent_config: Mapping[str, Any], prompt: str) -> Any:
    """The part of an LLM action's *context* its request sends beside *prompt*."""
    kind = agent_config.get("kind") or DEFAULT_ACTION_KIND
    if not isinstance(context, Mapping) or getattr(kind, "value", kind) != DEFAULT_ACTION_KIND:
        return context
    setting = agent_config.get(CONTEXT_BLOCK_KEY) or get_default(CONTEXT_BLOCK_KEY)
    if setting == "all" or (setting == "auto" and _record_has_its_own_message(agent_config)):
        return context
    if setting == "none":
        return {}
    try:
        template = PromptFormatter.get_raw_prompt(agent_config)
    except Exception as error:
        logger.debug("Context block kept whole: the prompt template did not load: %s", error)
        return context
    sent: Mapping[str, Any] = context
    for path in printed_fields(template or ""):
        sent = _without_printed(sent, path, prompt)
    return sent


@lru_cache(maxsize=256)
def printed_fields(template: str) -> tuple[tuple[str, ...], ...]:
    """The field paths an output tag at the top level of *template* prints as they are.

    A tag inside a block, loop, condition or macro may not render, and a filter changes
    the text, so neither counts. A top-level ``{% set a = b %}`` (an ``as:`` alias) is
    followed; a name set to anything else is a local value, not a field.
    """
    try:
        ast = Environment(extensions=PROMPT_EXTENSIONS).parse(escape_jinja_in_inline_code(template))  # nosec B701  # prompt text, not HTML
    except TemplateSyntaxError:
        return ()
    aliases: dict[str, str | None] = {}
    paths: list[tuple[str, ...]] = []
    for node in ast.body:
        if isinstance(node, nodes.Assign) and isinstance(node.target, nodes.Name):
            value = node.node
            aliases[node.target.name] = (
                aliases.get(value.name, value.name) if isinstance(value, nodes.Name) else None
            )
        elif isinstance(node, nodes.Output):
            for item in node.nodes:
                path = _field_path(item)
                if path is None or len(path) < 2:
                    continue
                root = aliases.get(path[0], path[0])
                if root is not None:
                    paths.append((root, *path[1:]))
    return tuple(dict.fromkeys(paths))


def _field_path(node: nodes.Node) -> tuple[str, ...] | None:
    if isinstance(node, nodes.Name):
        return (node.name,)
    if isinstance(node, nodes.Getattr):
        parent = _field_path(node.node)
        return None if parent is None else (*parent, node.attr)
    if (
        isinstance(node, nodes.Getitem)
        and isinstance(node.arg, nodes.Const)
        and isinstance(node.arg.value, str)
    ):
        parent = _field_path(node.node)
        return None if parent is None else (*parent, node.arg.value)
    return None


def _record_has_its_own_message(agent_config: Mapping[str, Any]) -> bool:
    """Whether the vendor sends the record in a message of its own, apart from the prompt."""
    config = PROVIDER_MESSAGE_CONFIGS.get(str(agent_config.get("model_vendor") or "").lower())
    if config is None:
        return False
    json_mode = agent_config.get("json_mode", get_default("json_mode"))
    role = config.json_role if json_mode else config.non_json_role
    return role is MessageRole.SYSTEM_PLUS_USER


def _without_printed(
    context: Mapping[str, Any], path: tuple[str, ...], prompt: str
) -> Mapping[str, Any]:
    """*context* without the field at *path*, when *prompt* holds the text it renders to."""
    parent: Any = context
    for key in path[:-1]:
        parent = parent.get(key) if isinstance(parent, Mapping) else None
    if not isinstance(parent, Mapping) or path[-1] not in parent:
        return context
    value = parent[path[-1]]
    # A repair prompt may not hold the rendered prompt; a field it lacks stays in the block.
    if value is None or str(value) not in prompt:
        return context
    return _popped(context, path)


def _popped(mapping: Mapping[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    """A copy of *mapping* without *path*; a namespace left empty goes too."""
    rest: dict[str, Any] = {}
    for key, value in mapping.items():
        if key != path[0]:
            rest[key] = value
        elif len(path) > 1:
            inner = _popped(value, path[1:])
            if inner:
                rest[key] = inner
    return rest
