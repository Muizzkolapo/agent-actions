"""Serialization/deserialization utilities for batch results."""

import json
from typing import Any

from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata


def serialize_results(results: list[BatchResult]) -> list[dict[str, Any]]:
    """Serialize BatchResult objects for JSON persistence.

    Args:
        results: Batch results to serialize

    Returns:
        List of dicts suitable for JSON serialization
    """
    serialized = []
    for r in results:
        d: dict[str, Any] = {
            "custom_id": r.custom_id,
            "content": r.content,
            "success": r.success,
        }
        if r.error:
            # Without this a failure carried across a deferred round arrives with
            # error=None and reports a generic "Batch processing failed" instead
            # of what the provider actually said.
            d["error"] = r.error
        if r.metadata:
            d["metadata"] = r.metadata
        if r.usage:
            d["usage"] = r.usage
        if r.recovery_metadata:
            d["recovery_metadata"] = r.recovery_metadata.to_dict()
        if r.exhausted:
            d["exhausted"] = True
        if r.raw_text is not None:
            d["raw_text"] = r.raw_text
        # Written by every serializer that keeps raw_text, so a reader can tell a state
        # an earlier version wrote (no text kept) from a result that has no text.
        d["text_kept"] = True
        serialized.append(d)
    return serialized


def _text_of_an_earlier_state(d: dict[str, Any]) -> str | None:
    """The answer text of a result an earlier version persisted, which kept no text.

    That version parsed every text answer as JSON and stored the parsed content, so the
    text is the content itself, or its JSON. A state this version wrote has `text_kept`,
    and a result in it without `raw_text` had no text.
    """
    if d.get("text_kept") or not d.get("success") or d.get("content") is None:
        return None
    content = d["content"]
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def deserialize_results(data: list[dict[str, Any]]) -> list[BatchResult]:
    """Deserialize BatchResult objects from JSON.

    Args:
        data: List of dicts from JSON

    Returns:
        List of BatchResult objects
    """
    results = []
    for d in data:
        recovery = None
        if d.get("recovery_metadata"):
            from agent_actions.processing.types import (
                EvaluationMetadata,
                ExpectationsMetadata,
            )

            rm = d["recovery_metadata"]
            retry = None
            evaluation = None
            expectations = None
            if rm.get("retry"):
                retry = RetryMetadata(**rm["retry"])
            if rm.get("evaluation"):
                evaluation = EvaluationMetadata(**rm["evaluation"])
            if rm.get("expectations"):
                expectations = ExpectationsMetadata(**rm["expectations"])
            recovery = RecoveryMetadata(
                retry=retry,
                evaluation=evaluation,
                expectations=expectations,
            )

        result = BatchResult(
            custom_id=d["custom_id"],
            content=d["content"],
            success=d["success"],
            error=d.get("error"),
            metadata=d.get("metadata"),
            usage=d.get("usage"),
            exhausted=d.get("exhausted", False),
            raw_text=d.get("raw_text", _text_of_an_earlier_state(d)),
        )
        result.recovery_metadata = recovery
        results.append(result)
    return results
