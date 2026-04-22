"""
Reproduction script for Bug #01: Retry exhaustion inside reprompt
silently misreported as validation pass.

Run from the repo root with the venv activated:
    python tests/manual/repro_bug_01_retry_exhaust_misreported.py

Expected output: demonstrates that when retry exhausts inside a
reprompt cycle, the RepromptResult reports passed=True, attempts=0,
exhausted=False — all lies.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_actions.errors import RateLimitError
from agent_actions.processing.recovery.reprompt import RepromptResult, RepromptService
from agent_actions.processing.recovery.retry import (
    RetryExhaustedException,
    RetryService,
)
from agent_actions.processing.recovery.validation import reprompt_validation


# ── Setup: a validation UDF that checks for a required field ──────────


@reprompt_validation("Response must contain 'summary' field")
def check_summary(response: dict) -> bool:
    return isinstance(response.get("summary"), str) and len(response["summary"]) > 0


# ── Scenario 1: Retry exhausts on FIRST reprompt attempt ─────────────


def scenario_1_retry_exhausts_first_attempt():
    """
    Retry exhausts immediately (all LLM calls hit 429).
    Reprompt should report: passed=False, exhausted=True.
    Actually reports: passed=True, attempts=0, exhausted=False.
    """
    print("=" * 70)
    print("SCENARIO 1: Retry exhausts on first reprompt attempt")
    print("=" * 70)

    call_count = 0

    retry_service = RetryService(max_attempts=2, base_delay=0.01, max_delay=0.01)
    reprompt_service = RepromptService(
        validation_name="check_summary",
        max_attempts=3,
        on_exhausted="return_last",
    )

    def llm_with_retry(prompt: str):
        """Simulates _invoke_with_retry_and_reprompt.llm_with_retry"""
        nonlocal call_count

        def fake_llm_call():
            nonlocal call_count
            call_count += 1
            raise RateLimitError(f"429 Too Many Requests (call #{call_count})")

        retry_result = retry_service.execute(fake_llm_call, context="test_action")

        if retry_result.exhausted:
            # This is what online.py:191-192 does
            raise RetryExhaustedException(retry_result)

        return retry_result.response

    result: RepromptResult = reprompt_service.execute(
        llm_operation=llm_with_retry,
        original_prompt="Summarize this text: ...",
        context="test_action",
    )

    print(f"\n  LLM calls made:     {call_count}")
    print(f"  result.response:    {result.response}")
    print(f"  result.executed:    {result.executed}")
    print(f"  result.attempts:    {result.attempts}")
    print(f"  result.passed:      {result.passed}")
    print(f"  result.exhausted:   {result.exhausted}")

    # Check for the bug
    bugs = []
    if result.passed is True:
        bugs.append("passed=True (WRONG — retry exhausted, nothing validated)")
    if result.attempts == 0:
        bugs.append("attempts=0 (WRONG — retry made 2 attempts)")
    if result.exhausted is False:
        bugs.append("exhausted=False (WRONG — retry was exhausted)")
    if result.executed is False:
        bugs.append("executed=False (MISLEADING — reported as 'guard skipped')")

    if bugs:
        print(f"\n  BUG CONFIRMED ({len(bugs)} issues):")
        for b in bugs:
            print(f"    - {b}")
    else:
        print("\n  No bug detected (fix may have been applied)")

    return len(bugs) > 0


# ── Scenario 2: First attempt succeeds but fails validation,
#    second attempt hits retry exhaustion ──────────────────────────────


def scenario_2_retry_exhausts_on_second_reprompt():
    """
    Attempt 1: LLM responds but validation fails.
    Attempt 2: Retry exhausts (provider starts rate-limiting).
    Reprompt should report: passed=False, exhausted=True, response=last_valid_response.
    Actually reports: passed=True, attempts=0, response=None.
    """
    print("\n" + "=" * 70)
    print("SCENARIO 2: Retry exhausts on SECOND reprompt attempt")
    print("=" * 70)

    call_count = 0
    succeed_first = True

    retry_service = RetryService(max_attempts=2, base_delay=0.01, max_delay=0.01)
    reprompt_service = RepromptService(
        validation_name="check_summary",
        max_attempts=3,
        on_exhausted="return_last",
    )

    def llm_with_retry(prompt: str):
        nonlocal call_count, succeed_first

        def fake_llm_call():
            nonlocal call_count, succeed_first
            call_count += 1
            if succeed_first:
                succeed_first = False
                # Return a response that FAILS validation (no 'summary' field)
                return {"detail": "some analysis but missing summary"}, True
            raise RateLimitError(f"429 Too Many Requests (call #{call_count})")

        retry_result = retry_service.execute(fake_llm_call, context="test_action")

        if retry_result.exhausted:
            raise RetryExhaustedException(retry_result)

        return retry_result.response

    result: RepromptResult = reprompt_service.execute(
        llm_operation=llm_with_retry,
        original_prompt="Summarize this text: ...",
        context="test_action",
    )

    print(f"\n  LLM calls made:     {call_count}")
    print(f"  result.response:    {result.response}")
    print(f"  result.executed:    {result.executed}")
    print(f"  result.attempts:    {result.attempts}")
    print(f"  result.passed:      {result.passed}")
    print(f"  result.exhausted:   {result.exhausted}")

    bugs = []
    if result.passed is True:
        bugs.append("passed=True (WRONG — attempt 1 failed validation, attempt 2 retry exhausted)")
    if result.attempts == 0:
        bugs.append("attempts=0 (WRONG — 1 validation attempt + 1 retry-exhausted attempt)")
    if result.response is None:
        bugs.append("response=None (WRONG — attempt 1's response was discarded)")

    if bugs:
        print(f"\n  BUG CONFIRMED ({len(bugs)} issues):")
        for b in bugs:
            print(f"    - {b}")
    else:
        print("\n  No bug detected (fix may have been applied)")

    return len(bugs) > 0


# ── Scenario 3: on_exhausted="raise" is bypassed ─────────────────────


def scenario_3_on_exhausted_raise_bypassed():
    """
    User configures on_exhausted="raise" expecting a RuntimeError.
    Retry exhausts → guard-skip path fires → no error raised.
    """
    print("\n" + "=" * 70)
    print("SCENARIO 3: on_exhausted='raise' is bypassed by retry exhaustion")
    print("=" * 70)

    retry_service = RetryService(max_attempts=1, base_delay=0.01, max_delay=0.01)
    reprompt_service = RepromptService(
        validation_name="check_summary",
        max_attempts=2,
        on_exhausted="raise",  # <-- user expects RuntimeError
    )

    def llm_with_retry(prompt: str):
        def fake_llm_call():
            raise RateLimitError("429 Too Many Requests")

        retry_result = retry_service.execute(fake_llm_call, context="test_action")

        if retry_result.exhausted:
            raise RetryExhaustedException(retry_result)

        return retry_result.response

    raised = False
    try:
        result = reprompt_service.execute(
            llm_operation=llm_with_retry,
            original_prompt="Summarize this text: ...",
            context="test_action",
        )
    except RuntimeError:
        raised = True
        result = None

    if raised:
        print("\n  RuntimeError raised as expected (fix may have been applied)")
    else:
        print(f"\n  result.passed:      {result.passed}")
        print(f"  result.exhausted:   {result.exhausted}")
        print(f"\n  BUG CONFIRMED:")
        print(f"    - on_exhausted='raise' was BYPASSED — no RuntimeError raised")
        print(f"    - User configured strict failure mode but got silent pass-through")

    return not raised


# ── Scenario 4: Verify the guard-skip path works correctly for
#    legitimate guard skips (should NOT be broken by a fix) ────────────


def scenario_4_legitimate_guard_skip():
    """
    A legitimate guard skip: LLM execution skipped because guard
    determined record doesn't need processing. Returns original data.
    This should return passed=True — NOT a bug.
    """
    print("\n" + "=" * 70)
    print("SCENARIO 4: Legitimate guard skip (should pass — baseline)")
    print("=" * 70)

    reprompt_service = RepromptService(
        validation_name="check_summary",
        max_attempts=2,
        on_exhausted="return_last",
    )

    def llm_with_guard_skip(prompt: str):
        # Guard determined this record doesn't need LLM processing
        # Return original data with executed=False
        return {"summary": "pre-existing summary", "status": "already_processed"}, False

    result: RepromptResult = reprompt_service.execute(
        llm_operation=llm_with_guard_skip,
        original_prompt="Summarize this text: ...",
        context="test_action",
    )

    print(f"\n  result.response:    {result.response}")
    print(f"  result.executed:    {result.executed}")
    print(f"  result.passed:      {result.passed}")

    if result.passed and not result.executed:
        print("\n  CORRECT — legitimate guard skip returns passed=True")
        print("  (Any fix for bug #01 must NOT break this path)")
    else:
        print("\n  UNEXPECTED — guard skip behavior changed")

    return False  # This scenario is not a bug


# ── Run all scenarios ─────────────────────────────────────────────────

if __name__ == "__main__":
    print("Bug #01 Reproduction: Retry exhaustion misreported as success")
    print("=" * 70)
    print()

    bugs_found = 0
    bugs_found += scenario_1_retry_exhausts_first_attempt()
    bugs_found += scenario_2_retry_exhausts_on_second_reprompt()
    bugs_found += scenario_3_on_exhausted_raise_bypassed()
    scenario_4_legitimate_guard_skip()

    print("\n" + "=" * 70)
    if bugs_found:
        print(f"RESULT: {bugs_found} scenario(s) confirmed the bug.")
        print("The reprompt loop cannot distinguish retry exhaustion from guard skip.")
        sys.exit(1)
    else:
        print("RESULT: No bugs found — fix may have been applied.")
        sys.exit(0)
