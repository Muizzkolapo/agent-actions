"""Centralized data-card rendering — shared constants, field classification,
and markdown formatting for LSP hover and HITL template injection.

The METADATA_KEYS set here is the single source of truth, mirrored in:
  - frontend: lib/data-card-utils.ts
  - HITL template: approval.html (injected via server context)
"""

from __future__ import annotations

import json
from typing import Any

# ── Metadata keys (single source of truth) ──────────────────────────────────

METADATA_KEYS: frozenset[str] = frozenset(
    {
        "source_guid",
        "lineage",
        "node_id",
        "metadata",
        "target_id",
        "parent_target_id",
        "root_target_id",
        "chunk_info",
        "_recovery",
        "_unprocessed",
        "_file",
    }
)

IDENTITY_KEYS: frozenset[str] = frozenset({"source_guid", "target_id"})

LONG_FORM_HINTS: frozenset[str] = frozenset(
    {
        "reasoning",
        "classification_reasoning",
        "description",
        "summary",
        "explanation",
        "rationale",
        "comment",
        "notes",
    }
)


# ── Field classification ────────────────────────────────────────────────────


def classify_field(key: str) -> str:
    """Return 'identity', 'content', or 'metadata'."""
    if key in IDENTITY_KEYS:
        return "identity"
    if key in METADATA_KEYS:
        return "metadata"
    return "content"


def classify_record(
    record: dict[str, Any],
) -> dict[str, list[tuple[str, Any]]]:
    """Partition a record into identity / content / metadata field groups."""
    groups: dict[str, list[tuple[str, Any]]] = {
        "identity": [],
        "content": [],
        "metadata": [],
    }
    for key, value in record.items():
        groups[classify_field(key)].append((key, value))
    return groups


# ── Value formatting ────────────────────────────────────────────────────────


def _humanize_key(key: str) -> str:
    """Convert snake_case to Title Case."""
    return key.replace("_", " ").title()


def _format_value(value: Any, max_length: int = 120) -> str:
    """Format a value for display, with optional truncation."""
    if value is None:
        return "_null_"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return f"{value:,}" if isinstance(value, int) else str(value)
    if isinstance(value, (dict, list)):
        s = json.dumps(value, ensure_ascii=False)
        if max_length and len(s) > max_length:
            return s[:max_length] + "\u2026"
        return s
    s = str(value)
    if max_length and len(s) > max_length:
        return s[:max_length] + "\u2026"
    return s


def _is_long_form(key: str) -> bool:
    lower = key.lower()
    return any(lower == h or lower.endswith("_" + h) for h in LONG_FORM_HINTS)


# ── Markdown card renderer (for LSP hover) ──────────────────────────────────


def render_card_markdown(
    record: dict[str, Any],
    *,
    action_name: str | None = None,
    max_fields: int = 12,
) -> str:
    """Render a single record as a markdown card suitable for IDE hover.

    Layout:
        **source_guid** `abc123...`
        ---
        **Field Label**: value
        ...
        ---
        _metadata: node_id, lineage, ..._

    When *action_name* is given and ``record["content"]`` is a namespaced
    dict (additive model), the content is unwrapped to show only that
    action's fields.
    """
    display = record
    if action_name:
        content = record.get("content")
        if (
            isinstance(content, dict)
            and action_name in content
            and isinstance(content[action_name], dict)
        ):
            # Flatten action fields into the record so classify_record
            # sees them as individual content fields, not as a nested
            # "content" blob.
            display = {k: v for k, v in record.items() if k != "content"}
            display.update(content[action_name])
    groups = classify_record(display)
    lines: list[str] = []

    # Identity header
    for key, value in groups["identity"]:
        lines.append(f"**{_humanize_key(key)}**: `{_format_value(value, 36)}`")

    if groups["identity"]:
        lines.append("---")

    # Content fields
    shown = 0
    for key, value in groups["content"]:
        if shown >= max_fields:
            remaining = len(groups["content"]) - shown
            lines.append(f"_...and {remaining} more fields_")
            break

        label = _humanize_key(key)

        if isinstance(value, (dict, list)):
            compact = json.dumps(value, ensure_ascii=False)
            if len(compact) <= 60:
                lines.append(f"**{label}**: `{compact}`")
            else:
                lines.append(f"**{label}**:")
                lines.append(f"```json\n{json.dumps(value, indent=2, ensure_ascii=False)}\n```")
        elif _is_long_form(key) and isinstance(value, str) and len(value) > 100:
            lines.append(f"**{label}**:")
            # Truncate very long prose in hover
            preview = value[:300] + ("\u2026" if len(value) > 300 else "")
            lines.append(f"> {preview}")
        else:
            lines.append(f"**{label}**: {_format_value(value, 80)}")

        shown += 1

    # Metadata footer
    meta_keys = [key for key, _ in groups["metadata"]]
    if meta_keys:
        if groups["content"]:
            lines.append("---")
        lines.append(f"_metadata: {', '.join(meta_keys)}_")

    return "\n\n".join(lines)
