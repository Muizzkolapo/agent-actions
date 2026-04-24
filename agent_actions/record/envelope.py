"""Unified record envelope -- single authority for record content assembly."""

from __future__ import annotations

from typing import Any


class RecordEnvelopeError(Exception):
    """Raised when a record envelope contract is violated."""

    pass


class RecordEnvelope:
    """Builds record content dicts. The ONLY place this happens.

    Every action type, every granularity, every strategy calls this.
    """

    @staticmethod
    def build(
        action_name: str,
        action_output: dict[str, Any],
        input_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a complete record with action output under its namespace.

        This is the primary entry point. Every code path that produces
        a record with action output calls this.

        When input_record is None (first action in pipeline, or test setup),
        returns ``{"content": {action_name: action_output}}`` with no
        source_guid.

        When input_record is provided, returns::

            {
                "source_guid": <from input_record>,
                "content": {
                    <...all upstream namespaces from input_record...>,
                    <action_name>: <action_output>
                }
            }

        If action_name already exists in content (retry/reprocessing),
        the new output overwrites the previous. This is intentional.
        """
        if not action_name:
            raise RecordEnvelopeError("action_name is required -- cannot build record without it")
        if not isinstance(action_output, dict):
            raise RecordEnvelopeError(
                f"action_output must be a dict, got {type(action_output).__name__} "
                f"for action '{action_name}'"
            )

        existing = _extract_existing(input_record)
        result: dict[str, Any] = {"content": {**existing, action_name: action_output}}
        if input_record and "source_guid" in input_record:
            result["source_guid"] = input_record["source_guid"]
        return result

    @staticmethod
    def build_content(
        action_name: str,
        action_output: dict[str, Any],
        existing_content: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build just the content dict (no source_guid, no record wrapper).

        For callers that already extracted existing_content from the record
        and operate at the content-dict level.

        Returns: ``{**existing_content, action_name: action_output}``
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
        """Build a record for a guard-skipped action.

        Null-valued namespace: ``content[action_name] = None``.
        All upstream namespaces preserved.

        Does NOT set ``_unprocessed`` or ``metadata`` -- those are framework
        concerns. Callers that need tombstone behavior add those fields
        after this call.
        """
        if not action_name:
            raise RecordEnvelopeError("action_name is required")
        existing = _extract_existing(input_record)
        result: dict[str, Any] = {"content": {**existing, action_name: None}}
        if input_record and "source_guid" in input_record:
            result["source_guid"] = input_record["source_guid"]
        return result

    @staticmethod
    def build_version_merge(
        version_contents: dict[str, dict[str, Any]],
        input_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a record for version fan-in merge.

        Each key in version_contents becomes a namespace, each value
        becomes that namespace's output.
        """
        if not version_contents:
            raise RecordEnvelopeError("version_contents is empty -- nothing to merge")
        existing = _extract_existing(input_record)
        result: dict[str, Any] = {"content": {**existing, **version_contents}}
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
