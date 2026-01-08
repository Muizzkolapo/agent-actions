"""
Failure injection for testing recovery (retry and reprompt).

Environment variables:
    RECOVERY_TEST_MODE: Type of failure to inject
        - "rate_limit": Inject RateLimitError (tests retry)
        - "network": Inject NetworkError (tests retry)
        - "malformed_json": Return malformed JSON (tests JSON repair)
        - "missing_fields": Return JSON missing required fields (tests reprompt)
        - "invalid_schema": Return JSON that doesn't match schema (tests reprompt)

    RECOVERY_FAILURE_RATE: Probability of failure (0.0-1.0), default 0.3
    RECOVERY_FAILURE_SEED: Random seed for reproducibility
"""

import json
import logging
import os
import random
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Load config at module level
_TEST_MODE = os.getenv("RECOVERY_TEST_MODE", "").lower()
_FAILURE_RATE = float(os.getenv("RECOVERY_FAILURE_RATE", "0.3"))
_FAILURE_SEED = os.getenv("RECOVERY_FAILURE_SEED", "")
_RNG = random.Random(int(_FAILURE_SEED) if _FAILURE_SEED.isdigit() else None)

# Track injection state
_injection_count = 0
_success_after = int(os.getenv("RECOVERY_SUCCESS_AFTER", "2"))  # Succeed after N failures

if _TEST_MODE:
    logger.info(
        f"Recovery failure injection enabled: mode={_TEST_MODE}, "
        f"rate={_FAILURE_RATE}, success_after={_success_after}"
    )


# Malformed JSON samples for testing repair
MALFORMED_JSON_SAMPLES = [
    # Markdown wrapped
    '```json\n{"name": "test", "value": 123}\n```',
    # Trailing comma
    '{"name": "test", "items": [1, 2, 3,]}',
    # Single quotes
    "{'name': 'test', 'value': 123}",
    # Unclosed bracket
    '{"name": "test", "items": [1, 2, 3',
    # Extra text
    'Here is the result: {"name": "test"} Hope this helps!',
    # Missing closing brace
    '{"name": "test", "value": 123',
]

# Invalid schema samples (missing fields, wrong types)
INVALID_SCHEMA_SAMPLES = [
    # Missing required fields
    {"partial": "data"},
    # Wrong types
    {"name": 123, "value": "should_be_number"},
    # Empty required fields
    {"name": "", "value": None},
]


def is_injection_enabled() -> bool:
    """Check if failure injection is enabled."""
    return bool(_TEST_MODE)


def should_inject_failure() -> bool:
    """Check if we should inject a failure based on rate."""
    global _injection_count

    if not _TEST_MODE:
        return False

    # Allow success after N failures (for testing recovery success)
    if _injection_count >= _success_after:
        _injection_count = 0  # Reset for next cycle
        return False

    if _RNG.random() < _FAILURE_RATE:
        _injection_count += 1
        return True

    return False


def inject_retry_failure(vendor: str = "test") -> None:
    """Inject a transient error for testing retry.

    Args:
        vendor: Vendor name for error context

    Raises:
        RateLimitError or NetworkError based on test mode
    """
    if not should_inject_failure():
        return

    from agent_actions.errors import RateLimitError, NetworkError

    if _TEST_MODE == "rate_limit":
        logger.info("[INJECTED] RateLimitError for retry testing")
        raise RateLimitError(
            "Injected rate limit for testing",
            context={"vendor": vendor, "injected": True, "retry_after": 1},
        )

    if _TEST_MODE == "network":
        logger.info("[INJECTED] NetworkError for retry testing")
        raise NetworkError(
            "Injected network error for testing",
            context={"vendor": vendor, "injected": True},
        )


def inject_reprompt_failure(
    valid_response: Any,
    schema: Optional[Dict[str, Any]] = None,
) -> Any:
    """Inject a validation error for testing reprompt.

    Args:
        valid_response: The valid response that would normally be returned
        schema: Optional schema to generate invalid response against

    Returns:
        Either the valid response or an injected invalid response
    """
    if not should_inject_failure():
        return valid_response

    if _TEST_MODE == "malformed_json":
        sample = _RNG.choice(MALFORMED_JSON_SAMPLES)
        logger.info(f"[INJECTED] Malformed JSON for reprompt testing: {sample[:50]}...")
        return sample

    if _TEST_MODE == "missing_fields":
        sample = _RNG.choice(INVALID_SCHEMA_SAMPLES)
        logger.info(f"[INJECTED] Invalid schema response for reprompt testing")
        return sample

    if _TEST_MODE == "invalid_schema":
        # Return something that's valid JSON but doesn't match expected schema
        logger.info("[INJECTED] Schema mismatch for reprompt testing")
        return {"_injected_error": True, "wrong_field": "unexpected"}

    return valid_response


def wrap_response_with_injection(
    response: Any,
    schema: Optional[Dict[str, Any]] = None,
) -> Any:
    """Wrap a response to potentially inject failures.

    Use this to wrap LLM client responses for testing.

    Args:
        response: The actual LLM response
        schema: Optional schema for generating invalid responses

    Returns:
        Either the original response or an injected failure
    """
    if not is_injection_enabled():
        return response

    # Check for retry-type failures first (these raise exceptions)
    if _TEST_MODE in ("rate_limit", "network"):
        inject_retry_failure()
        return response

    # Check for reprompt-type failures (these modify response)
    if _TEST_MODE in ("malformed_json", "missing_fields", "invalid_schema"):
        return inject_reprompt_failure(response, schema)

    return response


def reset_injection_state() -> None:
    """Reset injection state (useful between test runs)."""
    global _injection_count
    _injection_count = 0
