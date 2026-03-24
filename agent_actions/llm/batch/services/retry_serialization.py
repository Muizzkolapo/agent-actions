"""Serialization/deserialization utilities for batch results."""

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
        if r.metadata:
            d["metadata"] = r.metadata
        if r.recovery_metadata:
            d["recovery_metadata"] = r.recovery_metadata.to_dict()
        serialized.append(d)
    return serialized


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
            from agent_actions.processing.types import RepromptMetadata

            rm = d["recovery_metadata"]
            retry = None
            reprompt = None
            if rm.get("retry"):
                retry = RetryMetadata(**rm["retry"])
            if rm.get("reprompt"):
                reprompt = RepromptMetadata(**rm["reprompt"])
            recovery = RecoveryMetadata(retry=retry, reprompt=reprompt)

        result = BatchResult(
            custom_id=d["custom_id"],
            content=d["content"],
            success=d["success"],
            metadata=d.get("metadata"),
        )
        result.recovery_metadata = recovery
        results.append(result)
    return results
