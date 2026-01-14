#!/usr/bin/env python3
"""
Manual verification script for Recovery Implementation (RFC Recovery).
This script manually exercises the Retry and Reprompt logic using the RecordProcessor
with mocked LLM calls to simulate failures.
"""

import logging
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from unittest.mock import Mock, patch
from agent_actions.core.record_processor import RecordProcessor
from agent_actions.core.types import ProcessingContext, ProcessingMode
from agent_actions.core.reprompt_validation import reprompt_validation, _VALIDATION_REGISTRY
from agent_actions.errors import NetworkError, RateLimitError

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def test_online_retry():
    print("\n" + "=" * 50)
    print("Testing ONLINE RETRY Simulation")
    print("=" * 50)

    agent_config = {
        "name": "test_retry",
        "model_vendor": "openai",
        "model_name": "gpt-4",
        "retry": {"enabled": True, "max_attempts": 3, "on_exhausted": "return_last"},
    }

    processor = RecordProcessor(agent_config, "test_retry")
    context = ProcessingContext(
        agent_config=agent_config,
        agent_name="test_retry",
        mode=ProcessingMode.ONLINE,
        is_first_stage=True,
    )

    # Mock LLM to simulate 2 failures then success
    mock_calls = [0]

    def mock_run(*args, **kwargs):
        mock_calls[0] += 1
        attempt = mock_calls[0]
        if attempt <= 2:
            print(f"  [Attempt {attempt}] Simulating NetworkError")
            raise NetworkError("Connection reset")
        print(f"  [Attempt {attempt}] Simulating Success")
        return {"result": "success"}, True

    with patch(
        "agent_actions.utilities.processor.processor_helpers.run_dynamic_agent",
        side_effect=mock_run,
    ):
        with patch.object(
            processor,
            "_prepare_prompt",
            return_value=Mock(formatted_prompt="test", passthrough_fields={}),
        ):
            result = processor.process(item={"input": "test"}, context=context)

    print("\nResults:")
    print(f"- Total attempts: {mock_calls[0]}")
    if result.recovery_metadata and result.recovery_metadata.retry:
        retry_meta = result.recovery_metadata.retry
        print(f"- Recovery Metadata Present: Yes")
        print(f"- Recorded attempts: {retry_meta.attempts}")
        print(f"- Recorded reason: {retry_meta.reason}")
        print(f"- Succeeded: {retry_meta.succeeded}")

        if retry_meta.attempts == 3 and retry_meta.succeeded:
            print("✅ TEST PASSED: Retry logic worked correctly")
        else:
            print("❌ TEST FAILED: Incorrect retry metadata")
    else:
        print("❌ TEST FAILED: No recovery metadata found")


def test_online_reprompt():
    print("\n" + "=" * 50)
    print("Testing ONLINE REPROMPT Simulation")
    print("=" * 50)

    _VALIDATION_REGISTRY.clear()

    @reprompt_validation("Response must NOT contain 'forbidden'")
    def check_forbidden(response: dict) -> bool:
        return "forbidden" not in str(response).lower()

    agent_config = {
        "name": "test_reprompt",
        "model_vendor": "openai",
        "model_name": "gpt-4",
        "reprompt": {
            "validation": "check_forbidden",
            "max_attempts": 3,
            "on_exhausted": "return_last",
        },
    }

    processor = RecordProcessor(agent_config, "test_reprompt")
    context = ProcessingContext(
        agent_config=agent_config,
        agent_name="test_reprompt",
        mode=ProcessingMode.ONLINE,
        is_first_stage=True,
    )

    captured_prompts = []

    def mock_run(config, name, content, formatted_prompt, tools_path=None):
        captured_prompts.append(formatted_prompt)
        attempt = len(captured_prompts)

        if attempt <= 1:
            print(f"  [Attempt {attempt}] Returning INVALID response")
            return {"text": "This contains forbidden word"}, True

        print(f"  [Attempt {attempt}] Returning VALID response")
        return {"text": "This is acceptable"}, True

    with patch(
        "agent_actions.utilities.processor.processor_helpers.run_dynamic_agent",
        side_effect=mock_run,
    ):
        with patch.object(
            processor,
            "_prepare_prompt",
            return_value=Mock(formatted_prompt="Start", passthrough_fields={}),
        ):
            result = processor.process(item={"input": "test"}, context=context)

    print("\nResults:")
    print(f"- Total attempts: {len(captured_prompts)}")

    # Check feedback injection
    second_prompt = captured_prompts[1] if len(captured_prompts) > 1 else ""
    feedback_injected = "Your response failed validation" in second_prompt
    print(f"- Feedback injected in attempt 2: {feedback_injected}")
    if feedback_injected:
        print("  (Confirmed feedback message present in prompt)")
    else:
        print(f"  Prompt was: {second_prompt}")

    if result.recovery_metadata and result.recovery_metadata.reprompt:
        reprompt_meta = result.recovery_metadata.reprompt
        print(f"- Recovery Metadata Present: Yes")
        print(f"- Attempts: {reprompt_meta.attempts}")
        print(f"- Passed: {reprompt_meta.passed}")

        if feedback_injected and reprompt_meta.attempts == 2 and reprompt_meta.passed:
            print("✅ TEST PASSED: Reprompt logic worked correctly")
        else:
            print("❌ TEST FAILED: Logic mismatch")
    else:
        print("❌ TEST FAILED: No recovery metadata")


if __name__ == "__main__":
    print("STARTING MANUAL VERIFICATION")
    try:
        test_online_retry()
        test_online_reprompt()
    except Exception as e:
        logger.exception("Test crashed")
        sys.exit(1)
