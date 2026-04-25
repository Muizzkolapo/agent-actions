"""Unified record envelope -- single authority for record content assembly."""

from __future__ import annotations

from typing import Any

# Canonical set of framework fields that are NOT user business data.
# Used by record_processor (first-stage source wrapping), pipeline_file_mode
# (tool input stripping), and scope_namespace (metadata exclusion).
RECORD_FRAMEWORK_FIELDS: frozenset[str] = frozenset(
    {
        "source_guid",
        "target_id",
        "node_id",
        "lineage",
        "metadata",
        "content",
        "_unprocessed",
        "_recovery",
        "parent_target_id",
        "root_target_id",
        "chunk_info",
        "version_correlation_id",
    }
)


class RecordEnvelopeError(Exception):
    """Raised when a record envelope contract is violated."""

    pass


class RecordEnvelope:
    """Single authority for record content assembly."""

    @staticmethod
    def build(
        action_name: str,
        action_output: dict[str, Any],
        input_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a record wrapping *action_output* under *action_name*.

        Preserves upstream namespaces from *input_record* and carries
        ``source_guid``.  Collision on *action_name* overwrites.
        """
        if not action_name:
            raise RecordEnvelopeError("action_name is required")
        if not isinstance(action_output, dict):
            raise RecordEnvelopeError(
                f"action_output must be a dict, got {type(action_output).__name__} "
                f"for action '{action_name}'"
            )

        existing = _extract_existing(input_record)
        result: dict[str, Any] = {"content": {**existing, action_name: action_output}}
        return _carry_source_guid(result, input_record)

    @staticmethod
    def build_content(
        action_name: str,
        action_output: dict[str, Any],
        existing_content: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a content dict with *action_output* under *action_name*.

        No record wrapper or ``source_guid`` -- content level only.
        """
        if not action_name:
            raise RecordEnvelopeError("action_name is required")
        content = dict(existing_content) if existing_content else {}
        content[action_name] = action_output
        return content

    @staticmethod
    def build_skipped(
        action_name: str,
        input_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a record with a null namespace for a guard-skipped action.

        Does NOT set ``_unprocessed`` or ``metadata`` -- callers add those.
        """
        if not action_name:
            raise RecordEnvelopeError("action_name is required")
        existing = _extract_existing(input_record)
        result: dict[str, Any] = {"content": {**existing, action_name: None}}
        return _carry_source_guid(result, input_record)

    @staticmethod
    def build_version_merge(
        version_contents: dict[str, dict[str, Any]],
        input_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a record merging multiple version namespaces."""
        if not version_contents:
            raise RecordEnvelopeError("version_contents is empty -- nothing to merge")
        for key, value in version_contents.items():
            if not isinstance(value, dict):
                raise RecordEnvelopeError(
                    f"version_contents['{key}'] must be a dict, got {type(value).__name__}"
                )
        existing = _extract_existing(input_record)
        result: dict[str, Any] = {"content": {**existing, **version_contents}}
        return _carry_source_guid(result, input_record)


def _carry_source_guid(
    result: dict[str, Any], input_record: dict[str, Any] | None
) -> dict[str, Any]:
    """Copy source_guid from input_record to result if present."""
    if input_record and "source_guid" in input_record:
        result["source_guid"] = input_record["source_guid"]
    return result


def _extract_existing(input_record: dict[str, Any] | None) -> dict[str, Any]:
    """Extract the existing content dict from an input record."""
    if input_record is None:
        return {}
    content = input_record.get("content")
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise RecordEnvelopeError(
            f"input_record['content'] must be a dict, got {type(content).__name__}"
        )
    return content
