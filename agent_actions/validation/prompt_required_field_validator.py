"""Flag prompt refs to schema fields the producing action does not mark required."""

from __future__ import annotations

import logging
import re

from agent_actions.validation.prompt_ast import PromptASTAnalyzer

logger = logging.getLogger(__name__)

_JINJA_TAG = re.compile(r"{%-?.*?%}", re.DOTALL)
_TAG_NAME = re.compile(r"{%-?\s*(\w+)")


def _strip_if_blocks(template: str) -> str:
    """Return the template with every ``{% if %}``…``{% endif %}`` region removed.

    A depth counter tracks nesting so inner ``{% endif %}`` tags do not close an
    outer block early. Only text outside all if-blocks survives, so downstream
    extraction sees unconditional references only.
    """
    kept: list[str] = []
    depth = 0
    keep_from = 0
    for match in _JINJA_TAG.finditer(template):
        name_match = _TAG_NAME.match(match.group(0))
        name = name_match.group(1) if name_match else ""
        if name == "if":
            if depth == 0:
                kept.append(template[keep_from : match.start()])
            depth += 1
        elif name == "endif" and depth > 0:
            depth -= 1
            if depth == 0:
                keep_from = match.end()
    if depth == 0:
        kept.append(template[keep_from:])
    return "".join(kept)


def _optional_field_names(schema: dict) -> set[str]:
    """Names the producer declares but does not mark required."""
    return {f["id"] for f in schema.get("fields", []) if "id" in f and not f.get("required", False)}


def find_unguarded_required_refs(prompts: dict[str, str], schemas: dict[str, dict]) -> list[str]:
    """Return findings for unguarded prompt refs to non-required producer fields.

    A ref ``ns.field`` is flagged when ``ns`` has a producing schema, ``field``
    is declared by that schema but not marked required, and the ref is not
    inside an ``{% if %}`` block. Refs whose ``ns`` has no producing schema, or
    whose ``field`` the schema does not declare, belong to other checks and are
    left alone here.
    """
    analyzer = PromptASTAnalyzer()
    findings: list[str] = []
    for action_name, template in prompts.items():
        unconditional = _strip_if_blocks(template)
        try:
            tokens = analyzer.extract_variables(unconditional)
        except ValueError as exc:
            logger.debug("Skipping prompt scan for %s: %s", action_name, exc)
            continue
        for token in sorted(tokens):
            ns, _, remainder = token.partition(".")
            if not remainder or ns not in schemas:
                continue
            field = remainder.split(".", 1)[0].split("[", 1)[0]
            if field in _optional_field_names(schemas[ns]):
                findings.append(
                    f"{action_name}: prompt references '{token}' but producer '{ns}' "
                    f"does not guarantee '{field}' (not marked required, and no "
                    f"if-guard protects the ref)"
                )
    return findings
