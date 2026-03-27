"""
Failure injection for Ollama clients - testing retry mechanism.

This module provides controlled failure injection for testing retry behavior
in both online and batch modes. It uses a count-based approach (fail first N)
rather than the rate-based random approach in the shared
``agent_actions.llm.providers.failure_injection`` module.

Environment variables:
    OLLAMA_FAIL_FIRST_N=2           Fail first N calls/records (online + batch)

Usage:
    # Online mode - fail first 2 calls, 3rd succeeds
    OLLAMA_FAIL_FIRST_N=2 python -m agent_actions run workflow.yml

    # Batch mode - fail first 2 records in batch
    OLLAMA_FAIL_FIRST_N=2 python -m agent_actions run workflow.yml

To remove: Delete this file and remove imports from client.py and batch_client.py

See also: agent_actions.llm.providers.failure_injection (rate-based injection)
"""

import logging
import os

from agent_actions.errors import NetworkError

logger = logging.getLogger(__name__)

# Module-level state
_online_call_count = 0
_failed_batch_ids: set[str] = set()


def reset():
    """Reset injection state. Useful for tests."""
    global _online_call_count, _failed_batch_ids
    _online_call_count = 0
    _failed_batch_ids.clear()


def is_online_injection_enabled() -> bool:
    """Check if online failure injection is configured."""
    return int(os.getenv("OLLAMA_FAIL_FIRST_N", "0")) > 0


def is_batch_injection_enabled() -> bool:
    """Check if batch failure injection is configured."""
    return int(os.getenv("OLLAMA_FAIL_FIRST_N", "0")) > 0


def maybe_inject_online_failure(model: str) -> None:
    """
    Inject failure for online calls if configured.

    Call this AFTER the actual Ollama API call. If injection is triggered,
    raises NetworkError which RetryService will catch and retry.

    Args:
        model: Model name for error context

    Raises:
        NetworkError: If this call should fail (within first N calls)
    """
    global _online_call_count

    fail_n = int(os.getenv("OLLAMA_FAIL_FIRST_N", "0"))
    if fail_n <= 0:
        return

    _online_call_count += 1

    if _online_call_count <= fail_n:
        logger.info(
            "[INJECTION] Online failure %d/%d for model=%s",
            _online_call_count,
            fail_n,
            model,
        )
        raise NetworkError(
            f"Injected timeout (attempt {_online_call_count}/{fail_n})",
            context={"vendor": "ollama", "model": model, "injected": True},
        )


def should_fail_batch_record(custom_id: str, record_index: int) -> bool:
    """
    Check if a batch record should be failed.

    Call this for each record in batch processing. Returns True if the record
    should be skipped/failed to simulate missing results.

    Args:
        custom_id: The custom_id of the batch record
        record_index: Zero-based index of record in batch

    Returns:
        True if record should fail, False to process normally
    """
    global _failed_batch_ids

    fail_n = int(os.getenv("OLLAMA_FAIL_FIRST_N", "0"))
    if fail_n > 0 and record_index < fail_n:
        # Only fail on first encounter (not on retry)
        if custom_id not in _failed_batch_ids:
            _failed_batch_ids.add(custom_id)
            logger.info(
                "[INJECTION] Batch record %d failed (index < %d): %s",
                record_index,
                fail_n,
                custom_id,
            )
            return True

    return False


def get_injection_status() -> dict:
    """Get current injection status for debugging."""
    return {
        "online_call_count": _online_call_count,
        "online_fail_threshold": int(os.getenv("OLLAMA_FAIL_FIRST_N", "0")),
        "batch_fail_records": int(os.getenv("OLLAMA_FAIL_FIRST_N", "0")),
        "failed_batch_ids": list(_failed_batch_ids),
    }
