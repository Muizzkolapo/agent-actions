"""
Failure injection for Ollama clients - testing retry mechanism.

This module provides controlled failure injection for testing retry behavior
in both online and batch modes. It uses a count-based approach (fail first N)
rather than the rate-based random approach in the shared
``agent_actions.llm.providers.failure_injection`` module.

Environment variables:
    OLLAMA_FAIL_FIRST_N=2           Fail first N calls/records (online + batch)
    OLLAMA_FAIL_BATCH_NAMES=_retry  Batches whose name contains any of these
                                    comma-separated substrings fail terminally
                                    at the provider: submission runs nothing
                                    and status polls report "failed"

Usage:
    # Online mode - fail first 2 calls, 3rd succeeds
    OLLAMA_FAIL_FIRST_N=2 python -m agent_actions run workflow.yml

    # Batch mode - fail first 2 records in batch
    OLLAMA_FAIL_FIRST_N=2 python -m agent_actions run workflow.yml

    # Batch mode - every recovery retry batch dies at the provider
    OLLAMA_FAIL_BATCH_NAMES=_retry python -m agent_actions run workflow.yml

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


def maybe_inject_online_failure(model: str, vendor_slug: str = "ollama_local") -> None:
    """
    Inject failure for online calls if configured.

    Call this AFTER the actual Ollama API call. If injection is triggered,
    raises NetworkError which RetryService will catch and retry.

    Args:
        model: Model name for error context
        vendor_slug: Vendor identifier for error context

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
            "[INJECTION] Online failure %d/%d for model=%s vendor=%s",
            _online_call_count,
            fail_n,
            model,
            vendor_slug,
        )
        raise NetworkError(
            f"Injected timeout (attempt {_online_call_count}/{fail_n})",
            context={"vendor": vendor_slug, "model": model, "injected": True},
        )


_FAILED_BATCH_ID_MARKER = "injected_failure"


def failed_batch_id_for(batch_name: str) -> str | None:
    """Return a failure-marked batch id if this batch should die at the provider.

    Matching is by substring against ``OLLAMA_FAIL_BATCH_NAMES`` (comma-
    separated). The marker is encoded in the id itself so status polls in later
    processes can recognise the batch without shared state.
    """
    import uuid

    names = os.getenv("OLLAMA_FAIL_BATCH_NAMES", "")
    patterns = [p.strip() for p in names.split(",") if p.strip()]
    if not any(p in batch_name for p in patterns):
        return None
    batch_id = f"batch_{_FAILED_BATCH_ID_MARKER}_{uuid.uuid4().hex}"
    logger.info(
        "[INJECTION] Batch %r submitted as terminally failed at provider: %s",
        batch_name,
        batch_id,
    )
    return batch_id


def is_injected_failed_batch(batch_id: str) -> bool:
    """True if this batch id was minted by ``failed_batch_id_for``."""
    return _FAILED_BATCH_ID_MARKER in batch_id


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
