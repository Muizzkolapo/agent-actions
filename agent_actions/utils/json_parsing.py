"""Shared LLM JSON response parsing.

Every LLM provider — online and batch — must parse the model's text output
into a Python dict/list.  Models frequently wrap valid JSON in markdown code
fences or produce trailing-comma / unquoted-key variants.

This module is the **single source of truth** for that conversion:

    1. ``json.loads()``          — fast path for well-formed JSON
    2. Strip markdown fences     — ````` ```json … ``` ````` → inner text, retry
    3. ``json_repair``           — recover trailing commas, unquoted keys, etc.

Callers should use :func:`parse_llm_json` and branch on the return type:

* ``dict | list`` → parse succeeded
* ``str``         → all attempts failed; string is the original content
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Matches ```json … ``` or ``` … ``` with optional language tag.
# DOTALL so `.` matches newlines inside the fenced block.
_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:\w+)?\s*\n(.*?)\n\s*```\s*$",
    re.DOTALL,
)


def strip_code_fences(text: str) -> str:
    """Remove a single markdown code fence wrapper if present.

    Returns the inner content (stripped) when fences are found,
    or the original *text* unchanged otherwise.
    """
    match = _CODE_FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text


def parse_llm_json(content: str) -> dict[str, Any] | list[Any] | str:
    """Best-effort parse of an LLM text response into a Python object.

    Returns
    -------
    dict | list
        On success.
    str
        The original *content* when every strategy fails — the caller
        decides how to handle (e.g. return a ``_parse_error`` dict).
    """
    if not isinstance(content, str) or not content.strip():
        return content  # type: ignore[return-value]

    # 1. Fast path — well-formed JSON
    try:
        return json.loads(content)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown code fences and retry
    stripped = strip_code_fences(content)
    if stripped != content:
        try:
            return json.loads(stripped)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass

    # 3. json_repair — handles trailing commas, unquoted keys, etc.
    #    Guard: reject empty results ({}, []) — json_repair is aggressive and
    #    "repairs" arbitrary prose into empty containers, which is worse than
    #    signalling a parse failure.
    try:
        from json_repair import repair_json

        repaired = repair_json(content, return_objects=True, skip_json_loads=True)
        if isinstance(repaired, dict) and repaired:
            logger.debug("json_repair recovered valid dict from malformed LLM response")
            return repaired
        if isinstance(repaired, list) and repaired:
            logger.debug("json_repair recovered valid list from malformed LLM response")
            return repaired
    except Exception:
        logger.debug("json_repair failed", exc_info=True)

    # All strategies exhausted — return the original string.
    return content
